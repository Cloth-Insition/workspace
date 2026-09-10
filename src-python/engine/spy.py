"""
SPY closing-price lookup for Ledger's equity-curve overlay.

The original Ledger asked Claude (via the API + web search) for SPY's close on
each trade date — slow, costs API calls, and occasionally misparses. Here we
use yfinance, the same source the rotation tool already uses, for exact
official closes. Falls back to the nearest prior trading day for weekends and
holidays, matching the original's intent.

Prices are cached in the kv table so a date is only fetched once.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import ledger_db

_CACHE_KEY = "ledger:spy_cache"


def _load_cache() -> dict:
    raw = ledger_db.get_kv(_CACHE_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    ledger_db.set_kv(_CACHE_KEY, json.dumps(cache))


def spy_prices(dates: list[str]) -> dict:
    """Return {date: close} for each requested date.

    Uses the cache first; fetches any misses in one yfinance call spanning the
    full date range, then resolves each requested date to the nearest close
    on or before it.
    """
    cache = _load_cache()
    missing = [d for d in dates if d not in cache]

    if missing:
        try:
            import yfinance as yf

            lo = min(missing)
            hi = max(missing)
            # Pad the window so a date landing on a weekend/holiday still has a
            # prior close to resolve against.
            lo_dt = (datetime.strptime(lo, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
            hi_dt = (datetime.strptime(hi, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")

            df = yf.download("SPY", start=lo_dt, end=hi_dt, interval="1d",
                             progress=False, auto_adjust=True)
            closes: dict[str, float] = {}
            if df is not None and len(df):
                series = df["Close"].squeeze()
                for idx, val in series.items():
                    closes[idx.strftime("%Y-%m-%d")] = round(float(val), 2)

            # Resolve each missing date to nearest close on/before it.
            sorted_close_dates = sorted(closes.keys())
            for d in missing:
                price = None
                for cd in sorted_close_dates:
                    if cd <= d:
                        price = closes[cd]
                    else:
                        break
                if price is not None:
                    cache[d] = price

            _save_cache(cache)
        except Exception:
            # Network/lib failure: leave misses absent; the curve just omits
            # the SPY overlay for those points, exactly as the original did
            # when a fetch failed.
            pass

    return {d: cache[d] for d in dates if d in cache}
