"""FX history for the workspace FX chart.

Default pair is CHF=X — Yahoo's USD/CHF, quoted as CHF per 1 USD. So the line
falling means a USD balance is worth fewer francs.

Same shape as the other engine modules: pure data in, JSON-ready dict out, no
FastAPI imports here. Cached in memory so flipping between ranges in the UI
doesn't re-hit Yahoo every click.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import yfinance as yf

# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

DEFAULT_PAIR = "CHF=X"

PAIR_LABELS = {
    "CHF=X": "USD/CHF",
    "EURCHF=X": "EUR/CHF",
    "GBPCHF=X": "GBP/CHF",
    "EURUSD=X": "EUR/USD",
}

# range key -> (yfinance period, default interval)
RANGES: Dict[str, Tuple[str, str]] = {
    "5D": ("5d", "1h"),
    "1M": ("1mo", "1h"),
    "3M": ("3mo", "1d"),
    "6M": ("6mo", "1d"),
    "YTD": ("ytd", "1d"),
    "1Y": ("1y", "1d"),
    "5Y": ("5y", "1wk"),
    "MAX": ("max", "1mo"),
}

VALID_INTERVALS = {"1h", "60m", "1d", "1wk", "1mo"}

# Display timezone for intraday stamps. One line to change.
DISPLAY_TZ = "Europe/Zurich"

# Yahoo only serves ~730 days of hourly data.
INTRADAY_INTERVALS = {"1h", "60m"}
INTRADAY_SAFE_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "ytd"}

CACHE_TTL_SECONDS = 900  # 15 min
MAX_POINTS = 1500  # soft cap; thin beyond this so the chart stays responsive


class FxError(RuntimeError):
    """Raised when a pair/range can't be fetched. Endpoint turns this into a 502."""


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------

_cache: Dict[Tuple[str, str, str], Tuple[float, Dict[str, Any]]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _cache_get(key: Tuple[str, str, str]) -> Optional[Dict[str, Any]]:
    with _lock:
        hit = _cache.get(key)
    if hit is None:
        return None
    fetched_at, payload = hit
    if time.time() - fetched_at > CACHE_TTL_SECONDS:
        return None
    return payload


def _cache_put(key: Tuple[str, str, str], payload: Dict[str, Any]) -> None:
    with _lock:
        _cache[key] = (time.time(), payload)


# --------------------------------------------------------------------------
# fetch + shape
# --------------------------------------------------------------------------


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """Some yfinance versions hand back MultiIndex columns even for one ticker."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def _thin(rows: list, cap: Optional[int] = None) -> list:
    cap = cap or MAX_POINTS
    if len(rows) <= cap:
        return rows
    stride = -(-len(rows) // cap)  # ceil, so we land on the cap not well under it
    kept = rows[::stride]
    if kept[-1] is not rows[-1]:
        kept.append(rows[-1])
    return kept


def _stamp(idx, intraday: bool) -> str:
    ts = pd.Timestamp(idx)
    if intraday:
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        try:
            ts = ts.tz_convert(DISPLAY_TZ)
        except Exception:
            pass
        return ts.isoformat()
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.strftime("%Y-%m-%d")


def _download(pair: str, period: str, interval: str) -> pd.DataFrame:
    try:
        df = yf.Ticker(pair).history(
            period=period,
            interval=interval,
            auto_adjust=False,
            timeout=20,
        )
    except Exception as exc:  # network, rate limit, bad symbol
        raise FxError(f"{pair}: fetch failed ({exc})") from exc

    if df is None or df.empty:
        raise FxError(f"{pair}: Yahoo returned no rows for {period}/{interval}")

    df = _flatten(df)
    if "Close" not in df.columns:
        raise FxError(f"{pair}: no Close column (got {list(df.columns)})")

    df = df[~df["Close"].isna()]
    if df.empty:
        raise FxError(f"{pair}: every Close was empty for {period}/{interval}")
    return df


def fx_series(
    pair: str = DEFAULT_PAIR,
    range_key: str = "6M",
    interval: Optional[str] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Return a JSON-ready payload of closes for one FX pair."""
    range_key = (range_key or "6M").upper()
    if range_key not in RANGES:
        raise FxError(f"unknown range '{range_key}' (have {sorted(RANGES)})")

    period, default_interval = RANGES[range_key]
    interval = (interval or default_interval).lower()
    if interval not in VALID_INTERVALS:
        raise FxError(f"unsupported interval '{interval}'")
    if interval in INTRADAY_INTERVALS and period not in INTRADAY_SAFE_PERIODS:
        raise FxError(f"Yahoo won't serve {interval} bars over {period}")

    key = (pair, range_key, interval)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return {**cached, "cached": True}

    df = _download(pair, period, interval)
    intraday = interval in INTRADAY_INTERVALS

    closes = df["Close"].astype(float)
    points = _thin(
        [
            {"t": _stamp(idx, intraday), "rate": round(float(val), 6)}
            for idx, val in closes.items()
        ]
    )

    first = float(closes.iloc[0])
    last = float(closes.iloc[-1])
    change = last - first
    payload: Dict[str, Any] = {
        "pair": pair,
        "label": PAIR_LABELS.get(pair, pair.replace("=X", "")),
        "range": range_key,
        "interval": interval,
        "intraday": intraday,
        "tz": DISPLAY_TZ if intraday else None,
        "points": points,
        "summary": {
            "first": round(first, 6),
            "last": round(last, 6),
            "change": round(change, 6),
            "change_pct": round((change / first) * 100.0, 4) if first else 0.0,
            "high": round(float(closes.max()), 6),
            "low": round(float(closes.min()), 6),
            "count": len(points),
            "as_of": points[-1]["t"] if points else None,
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cached": False,
    }

    _cache_put(key, payload)
    return payload


def fx_ranges() -> Dict[str, Any]:
    """What the UI's range buttons should offer."""
    return {
        "default_pair": DEFAULT_PAIR,
        "pairs": [{"symbol": s, "label": l} for s, l in PAIR_LABELS.items()],
        "ranges": [
            {"key": k, "period": p, "interval": i} for k, (p, i) in RANGES.items()
        ],
    }


# --------------------------------------------------------------------------
# offline sanity check:  cd src-python && python3 -m engine.fx
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    out = fx_series(range_key="1M")
    print(json.dumps(out["summary"], indent=2))
    print(f"{out['label']}  {out['interval']}  {len(out['points'])} points")
    print("first:", out["points"][0], "\nlast: ", out["points"][-1])
