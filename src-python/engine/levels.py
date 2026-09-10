"""
S/R level detection — lifted verbatim from sr_scanner.py.

The detection maths (find_pivots, cluster_levels) is unchanged: it works and
it's the part you trust. What changed is the output. The standalone script
rendered an HTML ladder; here level_map() returns a plain dict the frontend
renders itself. That separation is the whole point — you verify the raw
levels, the UI just lays them out.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

PIVOT_SPAN = 3
CLUSTER_TOL_PCT = 1.0
MIN_TOUCHES = 2
CHUNK_PAUSE = 2.0
MAX_RETRIES = 3
RETRY_BACKOFF = 5.0


def find_pivots(highs: np.ndarray, lows: np.ndarray, span: int = PIVOT_SPAN):
    """Swing highs/lows: a bar that is the extreme within +/- span bars.

    The last `span` bars can't confirm a pivot — an unconfirmed pivot isn't a
    level yet. Unchanged from the original scanner.
    """
    pivots = []
    n = len(highs)
    for i in range(span, n - span):
        window_h = highs[i - span:i + span + 1]
        window_l = lows[i - span:i + span + 1]
        if highs[i] >= window_h.max():
            pivots.append((i, float(highs[i]), "H"))
        if lows[i] <= window_l.min():
            pivots.append((i, float(lows[i]), "L"))
    return pivots


def cluster_levels(pivots, tol_pct: float = CLUSTER_TOL_PCT,
                   min_touches: int = MIN_TOUCHES):
    """Greedy price clustering of pivots into levels. Unchanged."""
    if not pivots:
        return []

    by_price = sorted(pivots, key=lambda p: p[1])
    clusters = []
    current = [by_price[0]]

    for piv in by_price[1:]:
        mean_price = np.mean([p[1] for p in current])
        if abs(piv[1] - mean_price) / mean_price * 100.0 <= tol_pct:
            current.append(piv)
        else:
            clusters.append(current)
            current = [piv]
    clusters.append(current)

    levels = []
    for cl in clusters:
        if len(cl) < min_touches:
            continue
        prices = [p[1] for p in cl]
        idxs = [p[0] for p in cl]
        kinds = {p[2] for p in cl}
        levels.append({
            "level": float(np.mean(prices)),
            "lo": float(min(prices)),
            "hi": float(max(prices)),
            "touches": len(cl),
            "first_idx": min(idxs),
            "last_idx": max(idxs),
            "two_sided": ("H" in kinds and "L" in kinds),
        })
    return levels


def _fetch_one(ticker: str, lookback: str):
    """Single-ticker daily OHLCV via yfinance, with retry/backoff."""
    import yfinance as yf

    attempt, delay = 0, RETRY_BACKOFF
    while attempt < MAX_RETRIES:
        try:
            df = yf.download(ticker, period=lookback, interval="1d",
                             auto_adjust=False, progress=False)
            if df is not None and not df.dropna(how="all").empty:
                # Flatten a possible single-ticker MultiIndex.
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df
        except Exception:
            pass
        attempt += 1
        if attempt < MAX_RETRIES:
            time.sleep(delay)
            delay *= 2
    return None


def level_map(ticker: str, lookback: str = "1y", min_touches: int = MIN_TOUCHES,
              tolerance: float = CLUSTER_TOL_PCT, span: int = PIVOT_SPAN):
    """Every qualifying level for one ticker, structured for the UI ladder.

    Returns:
      {
        "ticker": str,
        "price": float | None,        # last close
        "levels": [                   # sorted top-down by price
          {"lo","hi","center","dist_pct","touches","two_sided","first","last"}
        ],
        "error": str | None,
      }
    """
    df = _fetch_one(ticker, lookback)
    if df is None:
        return {"ticker": ticker, "price": None, "levels": [],
                "error": f"No data returned for {ticker}."}

    df = df.dropna(subset=["High", "Low", "Close"])
    if len(df) < span * 2 + 20:
        return {"ticker": ticker, "price": None, "levels": [],
                "error": f"Not enough history for {ticker}."}

    price = float(df["Close"].iloc[-1])
    pivots = find_pivots(df["High"].to_numpy(float),
                         df["Low"].to_numpy(float), span)
    raw = cluster_levels(pivots, tolerance, min_touches)
    dates = df.index

    out = []
    for lv in raw:
        out.append({
            "lo": round(lv["lo"], 2),
            "hi": round(lv["hi"], 2),
            "center": round(lv["level"], 2),
            "dist_pct": round((price - lv["level"]) / lv["level"] * 100.0, 2),
            "touches": lv["touches"],
            "two_sided": lv["two_sided"],
            "first": dates[lv["first_idx"]].strftime("%Y-%m-%d"),
            "last": dates[lv["last_idx"]].strftime("%Y-%m-%d"),
        })
    out.sort(key=lambda lv: -lv["center"])

    return {"ticker": ticker, "price": round(price, 2),
            "levels": out, "error": None}


def proximity_scan(tickers: list[str], threshold_pct: float = 2.0,
                   lookback: str = "1y", min_touches: int = MIN_TOUCHES,
                   tolerance: float = CLUSTER_TOL_PCT, span: int = PIVOT_SPAN):
    """Across a universe of tickers, every level within threshold_pct of the
    current price — the morning scan from sr_scanner.py's default mode.

    Returns flat rows, one per (ticker, near-level), sorted closest-to-level
    first. Each row carries enough to render and to click through to the full
    ladder.

    Returns:
      {
        "rows": [{
          "ticker","price","level","lo","hi","dist_pct","side",
          "touches","two_sided","first","last"
        }, ...],
        "scanned": int,    # tickers that returned data
        "requested": int,  # tickers asked for
        "hits": int,       # rows found
      }
    """
    rows = []
    scanned = 0

    for t in tickers:
        df = _fetch_one(t, lookback)
        if df is None:
            continue
        df = df.dropna(subset=["High", "Low", "Close"])
        if len(df) < span * 2 + 20:
            continue
        scanned += 1

        price = float(df["Close"].iloc[-1])
        pivots = find_pivots(df["High"].to_numpy(float),
                             df["Low"].to_numpy(float), span)
        raw = cluster_levels(pivots, tolerance, min_touches)
        dates = df.index

        for lv in raw:
            dist = (price - lv["level"]) / lv["level"] * 100.0
            if abs(dist) > threshold_pct:
                continue
            rows.append({
                "ticker": t,
                "price": round(price, 2),
                "level": round(lv["level"], 2),
                "lo": round(lv["lo"], 2),
                "hi": round(lv["hi"], 2),
                "dist_pct": round(dist, 2),
                "side": "above" if dist >= 0 else "below",
                "touches": lv["touches"],
                "two_sided": lv["two_sided"],
                "first": dates[lv["first_idx"]].strftime("%Y-%m-%d"),
                "last": dates[lv["last_idx"]].strftime("%Y-%m-%d"),
            })

    # Closest to a level first — smallest absolute distance.
    rows.sort(key=lambda r: abs(r["dist_pct"]))

    return {"rows": rows, "scanned": scanned,
            "requested": len(tickers), "hits": len(rows)}
