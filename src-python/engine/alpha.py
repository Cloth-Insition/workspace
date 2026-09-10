"""
Jensen alpha for the Ledger — return you produced that the market did not.

The Ledger previously reported "Alpha" as (final strategy equity − final SPY
equity): the raw gap between two curves both indexed to 100. That is excess
return, not alpha, and it misleads in two opposite directions at once:

  1. No beta adjustment. A 2x-beta book in a +10% market is EXPECTED to return
     +20%; its true alpha is zero, but the old figure reported +10 and coloured
     it green.
  2. No deployment adjustment. The equity curve compounds account impact, so it
     reflects partially-deployed capital, while the SPY line is 100% invested
     throughout. A book averaging 20% deployment was being measured against a
     fully invested benchmark.

Because the two errors push opposite ways you cannot even sign the bias without
knowing average deployment. This module replaces it with a proper CAPM
decomposition at the account level.

Per trade i:

    w_i    = positionDollars / accountValueAtEntry     account weight
    r_i    = exitPrice / entryPrice - 1                price return
    m_i    = SPY return over [entryDate, exitDate]
    beta_i = OLS beta of the ticker vs SPY, trailing daily
    rf_i   = risk-free return over the holding window

    expected_i = rf_i + beta_i * (m_i - rf_i)          CAPM expectation
    alpha_i    = r_i - expected_i                      per unit of capital
    contrib_i  = w_i * alpha_i                         account-level points

Summing contrib_i gives total alpha in percentage points of the account, and it
decomposes cleanly:

    account return = market-explained + alpha        (+ cash, see below)

The deployment problem dissolves on its own: at 10% deployment with beta 1, a
+10% SPY move only explains 1% of your account, because your market exposure
was 0.1 — not 1.0. Uninvested capital earns rf and cancels out of the alpha
term, so alpha is unaffected by how much cash you held.

Risk-free rate: RISK_FREE_ANNUAL below, defaulting to 0. Over swing-trade
horizons rf is small, but it is not free — with average account beta below 1
(normal when partially deployed) setting rf=0 OVERSTATES alpha by roughly
rf*(1-beta) over the period. Set it to your actual cash rate for a stricter
number; the endpoint accepts an override.

Sign convention: positive alpha means you beat what your market exposure alone
would have produced. That is the number to judge yourself on.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

# Beta/price machinery is shared with Luck Check so the two tools cannot drift.
from engine.luck import (
    MIN_BETA_OBS,
    beta_rho,
    daily_returns,
    fetch_closes,
    window_return,
)

BENCHMARK = "SPY"
BETA_LOOKBACK = "1y"
RISK_FREE_ANNUAL = 0.0   # see module docstring
DAYS_YEAR = 365.0


class AlphaError(RuntimeError):
    """Raised when alpha cannot be computed at all. Endpoint turns this into 502."""


def _period_for(earliest: str) -> str:
    """yfinance period long enough to cover the oldest trade plus beta window."""
    try:
        d0 = datetime.strptime(earliest, "%Y-%m-%d")
    except Exception:
        return "2y"
    years = (datetime.now() - d0).days / DAYS_YEAR
    for cutoff, period in ((1.0, "2y"), (4.0, "5y"), (9.0, "10y")):
        if years <= cutoff:
            return period
    return "max"


def _calendar_days(a: str, b: str) -> int:
    try:
        d0 = datetime.strptime(a, "%Y-%m-%d")
        d1 = datetime.strptime(b, "%Y-%m-%d")
        return max(0, (d1 - d0).days)
    except Exception:
        return 0


def _weight(t: dict) -> Optional[float]:
    """Account weight of the position. None when the ledger row can't support it."""
    try:
        acct = float(t.get("accountValueAtEntry") or 0.0)
        pos = float(t.get("positionDollars") or 0.0)
    except (TypeError, ValueError):
        return None
    if acct <= 0:
        return None
    return pos / acct


def compute_alpha(
    trades: List[dict],
    risk_free_annual: float = RISK_FREE_ANNUAL,
) -> Dict[str, Any]:
    """CAPM decomposition of a trade ledger. See module docstring."""
    usable = [t for t in trades if t.get("entryDate") and t.get("exitDate")]
    if not usable:
        raise AlphaError("No closed trades with both entry and exit dates.")

    earliest = min(t["entryDate"] for t in usable)
    spy = fetch_closes(BENCHMARK, _period_for(earliest))
    if spy is None or len(spy) == 0:
        raise AlphaError("Could not fetch SPY history for the benchmark.")
    spy_ret = daily_returns(spy)

    closes_cache: Dict[str, Any] = {}
    beta_cache: Dict[str, Any] = {}

    rows: List[Dict[str, Any]] = []
    total_alpha = 0.0
    total_market = 0.0
    total_impact = 0.0
    exposure_sum = 0.0
    scored = 0
    skipped: List[Dict[str, str]] = []

    for t in usable:
        ticker = str(t.get("ticker", "")).strip().upper()
        row: Dict[str, Any] = {
            "ticker": ticker,
            "entryDate": t["entryDate"],
            "exitDate": t["exitDate"],
            "weight": None, "r_trade": None, "r_spy": None, "beta": None,
            "rf": None, "expected": None, "alpha": None,
            "alpha_contrib": None, "market_contrib": None, "impact": None,
            "skipped": None,
        }

        w = _weight(t)
        if w is None:
            row["skipped"] = "missing or zero accountValueAtEntry"
            skipped.append({"ticker": ticker, "reason": row["skipped"]})
            rows.append(row)
            continue

        try:
            entry_px = float(t["entryPrice"])
            exit_px = float(t["exitPrice"])
        except (TypeError, ValueError, KeyError):
            row["skipped"] = "missing entry/exit price"
            skipped.append({"ticker": ticker, "reason": row["skipped"]})
            rows.append(row)
            continue
        if entry_px == 0:
            row["skipped"] = "zero entry price"
            skipped.append({"ticker": ticker, "reason": row["skipped"]})
            rows.append(row)
            continue

        r_trade = exit_px / entry_px - 1.0
        row["weight"] = w
        row["r_trade"] = r_trade
        row["impact"] = w * r_trade

        m = window_return(spy, t["entryDate"], t["exitDate"])
        if m is None:
            row["skipped"] = "no SPY price for this window"
            skipped.append({"ticker": ticker, "reason": row["skipped"]})
            rows.append(row)
            continue
        row["r_spy"] = m

        # Beta vs SPY, cached per ticker across trades in this request.
        if ticker not in beta_cache:
            if ticker == BENCHMARK:
                # Trading the benchmark: beta is 1 by definition, no estimation.
                beta_cache[ticker] = 1.0
            else:
                closes = closes_cache.get(ticker)
                if closes is None:
                    closes = fetch_closes(ticker, BETA_LOOKBACK)
                    closes_cache[ticker] = closes
                if closes is None or len(closes) <= MIN_BETA_OBS:
                    beta_cache[ticker] = None
                else:
                    b, _rho, _n = beta_rho(daily_returns(closes), spy_ret)
                    beta_cache[ticker] = b
        beta = beta_cache[ticker]
        if beta is None:
            # Fail loudly per trade rather than silently assuming beta = 1,
            # which would quietly attribute market return to skill (or vice
            # versa) on exactly the illiquid names where it matters most.
            row["skipped"] = "not enough history to estimate beta"
            skipped.append({"ticker": ticker, "reason": row["skipped"]})
            rows.append(row)
            continue

        rf = risk_free_annual * (_calendar_days(t["entryDate"], t["exitDate"]) / DAYS_YEAR)
        expected = rf + beta * (m - rf)
        alpha_i = r_trade - expected

        row["beta"] = beta
        row["rf"] = rf
        row["expected"] = expected
        row["alpha"] = alpha_i
        row["alpha_contrib"] = w * alpha_i
        row["market_contrib"] = w * expected

        total_alpha += w * alpha_i
        total_market += w * expected
        total_impact += w * r_trade
        exposure_sum += w * beta
        scored += 1
        rows.append(row)

    if scored == 0:
        raise AlphaError(
            "No trade could be scored — check that SPY history covers your date "
            "range and that tickers have enough price history for a beta estimate."
        )

    avg_exposure = exposure_sum / scored

    # Buy-and-hold SPY over the same span, for context only. This is NOT the
    # alpha comparison — it is the naive benchmark the old metric used, kept so
    # the two can be seen side by side.
    latest = max(t["exitDate"] for t in usable)
    spy_span = window_return(spy, earliest, latest)

    return {
        "n_trades": len(usable),
        "n_scored": scored,
        "n_skipped": len(skipped),
        "skipped": skipped,
        "benchmark": BENCHMARK,
        "risk_free_annual": risk_free_annual,
        # The decomposition. total_impact = market_explained + alpha.
        "total_impact": total_impact,
        "market_explained": total_market,
        "alpha": total_alpha,
        "avg_beta_exposure": avg_exposure,
        "spy_buy_hold": spy_span,
        "period_start": earliest,
        "period_end": latest,
        "trades": rows,
    }
