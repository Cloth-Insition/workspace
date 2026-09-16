"""
Sector rotation fetch — lifted from rotation.py.

The standalone script fetched every sector ETF plus its top holdings, embedded
the price series in an HTML file, and computed returns/breadth in the browser.
Here scan() does the fetch and returns the same payload as JSON. The frontend
does the return/breadth maths (same logic, now in TS) and — crucially — makes
the holdings clickable, which is what wires rotation into the level ladder.

Holdings are deliberately a static fallback list so the sidecar has no scraping
dependency. The live yfinance holdings lookup from the original is kept as a
best-effort upgrade.
"""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd

SECTORS = {
    "XLK":  "Technology",
    "XLC":  "Communication Svcs",
    "XLY":  "Consumer Disc.",
    "XLF":  "Financials",
    "XLV":  "Health Care",
    "XLI":  "Industrials",
    "XLE":  "Energy",
    "XLB":  "Materials",
    "XLP":  "Consumer Staples",
    "XLU":  "Utilities",
    "XLRE": "Real Estate",
    "SPY":  "S&P 500 (ref)",
}

HOLDINGS = {
    "XLK":  ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "CSCO", "ADBE",
             "AMD", "ACN", "IBM", "TXN", "QCOM", "INTU", "NOW", "PLTR", "MU", "AMAT"],
    "XLC":  ["META", "GOOGL", "NFLX", "TMUS", "DIS", "CMCSA", "VZ", "T",
             "CHTR", "EA", "TTWO", "WBD", "LYV"],
    "XLY":  ["AMZN", "TSLA", "HD", "MCD", "BKNG", "LOW", "TJX", "SBUX",
             "NKE", "ORLY", "CMG", "MAR", "GM", "AZO", "RCL"],
    "XLP":  ["PG", "COST", "WMT", "KO", "PEP", "PM", "MDLZ", "MO", "CL",
             "TGT", "KMB", "GIS", "KDP", "STZ"],
    "XLE":  ["XOM", "CVX", "COP", "WMB", "EOG", "SLB", "PSX", "MPC", "KMI",
             "OKE", "VLO", "HES", "OXY", "BKR", "HAL"],
    "XLF":  ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI",
             "AXP", "C", "BLK", "SCHW", "CB", "PGR"],
    "XLV":  ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "ISRG",
             "AMGN", "DHR", "PFE", "BSX", "VRTX", "SYK", "GILD"],
    "XLI":  ["GE", "CAT", "RTX", "UBER", "HON", "UNP", "ETN", "BA", "DE",
             "LMT", "ADP", "PH", "GD", "TT", "MMM"],
    "XLB":  ["LIN", "SHW", "APD", "ECL", "FCX", "NEM", "CTVA", "MLM",
             "VMC", "DOW", "DD", "PPG", "NUE"],
    "XLRE": ["PLD", "AMT", "EQIX", "WELL", "SPG", "O", "PSA", "CCI",
             "DLR", "EXR", "VICI", "AVB", "CBRE", "IRM"],
    "XLU":  ["NEE", "SO", "DUK", "CEG", "SRE", "AEP", "VST", "D", "PEG",
             "EXC", "XEL", "ED", "WEC"],
}

HISTORY_PERIOD = "1y"
MONTH_BARS = 21
# The volume panel reads a year; the per-ticker close series the table and
# sector paths use stays at roughly a quarter, or the payload (and the cached
# copy of it) grows several-fold for data nothing displays.
SERIES_BARS = 70


def _fetch_series(ticker: str, period: str):
    """Daily [close, dollar_volume] history, cleaned. None on failure.

    Returns {"close": [[date, close], ...], "dvol": [[date, price*volume], ...]}
    Dollar volume (price × shares) is what we aggregate — it's comparable across
    tickers in a way raw share counts are not.
    """
    try:
        import yfinance as yf
        d = yf.download(ticker, period=period, interval="1d",
                        progress=False, auto_adjust=True)
        if d is not None and len(d) > 0:
            close = d["Close"].squeeze().dropna()
            vol = d["Volume"].squeeze() if "Volume" in d else None
            if len(close) > 0:
                closes = [[idx.strftime("%Y-%m-%d"), round(float(v), 4)]
                          for idx, v in close.items()]
                dvol = []
                if vol is not None:
                    for idx, c in close.items():
                        v = vol.get(idx)
                        if v is not None and not (isinstance(v, float) and v != v):
                            dvol.append([idx.strftime("%Y-%m-%d"),
                                         float(c) * float(v)])
                return {"close": closes, "dvol": dvol}
    except Exception:
        pass
    return None


def _daily_direction(series_full, sector_meta):
    """Per-session market direction, from data the scan already fetched.

    breadth = how many of the ~171 holdings closed up on the day, the same
    "share of names up" the sector table's breadth column means, applied
    daily across the whole universe instead of per sector over a span.
    Each ticker is compared against its own previous bar, so a ticker with
    a gap in its history does not skew the day.

    Returns (up_per_date, counted_per_date, spy_pct_per_date).
    """
    holdings = {h for meta in sector_meta.values() for h in meta.get("holdings", [])}
    up: dict[str, int] = {}
    total: dict[str, int] = {}
    for t in holdings:
        prev = None
        for date, close in series_full.get(t, {}).get("close", []):
            if prev is not None:
                total[date] = total.get(date, 0) + 1
                if close > prev:
                    up[date] = up.get(date, 0) + 1
            prev = close

    spy_pct: dict[str, float] = {}
    prev = None
    for date, close in series_full.get("SPY", {}).get("close", []):
        if prev:
            spy_pct[date] = round((close / prev - 1.0) * 100.0, 2)
        prev = close
    return up, total, spy_pct


def _build_volume(series_full, sector_meta):
    """Aggregate dollar volume into chart-ready figures.

    Returns:
      {
        "daily": [                       # every session fetched, oldest first
          {"d": date, "v": dollar_volume, "up": n_up, "n": n_counted,
           "spy": pct_change_or_null},
          ...
        ],
        "sectors": [
          {"etf","name","today","avg20","rel"},  # today vs its own 20-day avg
          ...
        ],
        "today": str | None,           # the most recent date present
        "today_is_latest": bool,
      }
    """
    # Universe-wide daily totals: sum dollar volume across every ticker per date.
    daily_totals: dict[str, float] = {}
    for t, sd in series_full.items():
        for date, dv in sd.get("dvol", []):
            daily_totals[date] = daily_totals.get(date, 0.0) + dv

    dates_sorted = sorted(daily_totals.keys())
    today = dates_sorted[-1] if dates_sorted else None

    up, counted, spy_pct = _daily_direction(series_full, sector_meta)
    daily = [{
        "d": d,
        "v": daily_totals[d],
        "up": up.get(d, 0) if counted.get(d) else None,
        "n": counted.get(d) or None,
        "spy": spy_pct.get(d),
    } for d in dates_sorted]

    # Per-sector: today's dollar volume vs that sector's own 20-day average,
    # so a sector punching above its weight stands out even on a quiet day.
    sector_rows = []
    for etf, meta in sector_meta.items():
        if etf == "SPY":
            continue
        holds = meta.get("holdings", [])
        # Build sector daily totals across its holdings.
        sdaily: dict[str, float] = {}
        for h in holds:
            for date, dv in series_full.get(h, {}).get("dvol", []):
                sdaily[date] = sdaily.get(date, 0.0) + dv
        if not sdaily:
            continue
        sdates = sorted(sdaily.keys())
        today_v = sdaily.get(today, 0.0) if today else 0.0
        # 20-day average excluding today.
        prior = [sdaily[d] for d in sdates if d != today][-20:]
        avg20 = sum(prior) / len(prior) if prior else 0.0
        rel = (today_v / avg20) if avg20 else 0.0
        sector_rows.append({
            "etf": etf,
            "name": meta["name"],
            "today": today_v,
            "avg20": avg20,
            "rel": round(rel, 2),
        })

    # Sort sectors by relative volume — where the action is concentrated today.
    sector_rows.sort(key=lambda r: -r["rel"])

    return {
        "daily": daily,
        "sectors": sector_rows,
        "today": today,
        "today_is_latest": True,
    }


def scan(period: str | None = None):
    """Fetch ETFs + holdings, return the structured rotation payload.

    The shape mirrors the original dashboard's embedded DATA object so the
    frontend's return/breadth maths is a direct port of the in-browser JS.
    """
    period = period or HISTORY_PERIOD
    series = {}        # close-only, for the existing return/breadth maths
    series_full = {}   # close + dvol, used to build the volume block
    sector_meta = {}
    all_tickers = list(SECTORS.keys())

    for etf in SECTORS:
        if etf == "SPY":
            continue
        holds = HOLDINGS.get(etf, [])
        sector_meta[etf] = {"name": SECTORS[etf], "holdings": holds}
        for h in holds:
            if h not in all_tickers:
                all_tickers.append(h)
    sector_meta["SPY"] = {"name": SECTORS["SPY"], "holdings": []}

    ok = 0
    for t in all_tickers:
        sd = _fetch_series(t, period)
        if sd:
            # series_full keeps the whole year for the volume panel's daily
            # breadth; series ships only the recent window the table draws.
            series[t] = sd["close"][-SERIES_BARS:]
            series_full[t] = sd
            ok += 1
        time.sleep(0.3)

    volume = _build_volume(series_full, sector_meta)

    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "generated_human": datetime.now().strftime("%A %d %B %Y, %H:%M"),
        "sectors": sector_meta,
        "series": series,
        "volume": volume,
        "month_bars": MONTH_BARS,
        "fetched": ok,
        "total": len(all_tickers),
        "error": None if ok else "No tickers returned data (Yahoo may be throttling).",
    }
