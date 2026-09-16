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
            "idxs": sorted(idxs),          # every touch bar, for volume stats
            "two_sided": ("H" in kinds and "L" in kinds),
        })
    return levels


# ---------------------------------------------------------------------------
# Level description. The detection above (find_pivots, cluster_levels) is
# deliberately untouched — it is the part that is trusted and that the eye is
# trained on. Everything below only *describes* levels that detection already
# found, so the same levels come out, carrying more information.
#
# Everything here reads OHLCV the scan already downloads. No extra requests.

ATR_PERIOD = 14
APPROACH_BARS = 5        # a trading week: is price closing in on the level?
FRESH_BARS = 120         # a touch older than this adds nothing to freshness


def atr_series(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """Wilder's ATR. The yardstick for 'is this market calm or fast', which is
    what turns a fixed 1% threshold into one that means the same thing in
    both."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def describe_level(df: pd.DataFrame, lv: dict, price: float, atr: float,
                   med_volume: float, all_levels: list[dict]) -> dict:
    """Measure one level: how strong, how fresh, how clean, how soon it gets
    tested, how much room beyond. Plain numbers for the UI to sort on."""
    closes = df["Close"].to_numpy(float)
    volumes = df["Volume"].to_numpy(float) if "Volume" in df else None
    n = len(closes)
    center, lo, hi = lv["level"], lv["lo"], lv["hi"]

    dist_pct = (price - center) / center * 100.0
    dist_atr = (price - center) / atr if atr and atr > 0 else None

    bars_since_last = n - 1 - lv["last_idx"]
    bars_since_first = n - 1 - lv["first_idx"]

    # Participation: volume across every touch bar vs this ticker's median.
    touch_vol_rel = None
    if volumes is not None and med_volume:
        idxs = [i for i in lv.get("idxs", []) if 0 <= i < n]
        if idxs:
            touch_vol_rel = float(np.mean(volumes[idxs]) / med_volume)

    # Cleanliness: full traversals of the level's BAND, not wiggles across its
    # centre. Oscillating inside the band is what a level looks like when it is
    # working; closing clean through it from one side to the other is not.
    seg = closes[lv["first_idx"]:]
    traversals = 0
    side = 0
    for c in seg:
        if c > hi and side <= 0:
            if side < 0:
                traversals += 1
            side = 1
        elif c < lo and side >= 0:
            if side > 0:
                traversals += 1
            side = -1

    # Imminence: at the pace of the last fortnight, how many sessions until
    # price reaches the level? Only meaningful when it is heading that way,
    # which is the question the morning scan is really asking.
    pace = float(np.mean(np.abs(np.diff(closes[-11:])))) if n > 11 else 0.0
    moving_toward = None
    eta_bars = None
    if n > APPROACH_BARS:
        was = closes[-1 - APPROACH_BARS]
        # Direction, not shrinking distance. Price that falls straight through
        # a level ends up nearer it in absolute terms while actually leaving it
        # behind — the level is now overhead, and calling that "approaching"
        # promotes exactly the setups that already happened without you.
        rising = price > was
        moving_toward = bool(rising if center >= price else not rising)
        if moving_toward and pace > 0:
            eta_bars = round(abs(price - center) / pace, 1)

    # Room: nearest level beyond this one, and the one behind it. Nothing
    # beyond means clear air, which is the most room there is — not the least.
    others = sorted(l["level"] for l in all_levels if l["level"] != center)
    beyond = next((l for l in others if l > center), None) if center >= price         else next((l for l in reversed(others) if l < center), None)
    behind = next((l for l in reversed(others) if l < price), None) if center >= price         else next((l for l in others if l > price), None)

    def gap_atr(target):
        if target is None or not atr or atr <= 0:
            return None
        return round(abs(target - center) / atr, 2)

    return {
        "dist_pct": round(dist_pct, 2),
        "dist_atr": round(dist_atr, 2) if dist_atr is not None else None,
        "bars_since_last": int(bars_since_last),
        "bars_since_first": int(bars_since_first),
        "touch_vol_rel": round(touch_vol_rel, 2) if touch_vol_rel else None,
        "traversals": traversals,
        "moving_toward": moving_toward,
        "eta_bars": eta_bars,
        "room_atr": gap_atr(beyond),          # None = nothing beyond = clear air
        "behind_atr": gap_atr(behind),
    }


# Score weights. A starting point, NOT validated: nothing yet proves touches
# matter more than fresh volume. Components come back with the score so the
# ranking can be argued with, sorted around, or ignored entirely.
SCORE_WEIGHTS = {
    "proximity": 0.20,      # near enough to matter at all
    "strength": 0.20,       # more touches
    "freshness": 0.15,      # touched recently
    "imminence": 0.15,      # heading there, and soon at this pace
    "cleanliness": 0.12,    # price has not closed clean through it
    "participation": 0.10,  # touches happened on real volume
    "room": 0.08,           # clear air beyond it
}
NEAR_ATR = 6.0              # beyond this many ATR a level is not today's problem
ETA_SOON_BARS = 3.0         # arriving within ~3 sessions is as urgent as it scores
ETA_FAR_BARS = 15.0         # beyond a fortnight away adds nothing


def score_level(a: dict, touches: int) -> dict:
    """Blend the measurements into one sortable 0-100 number, returning the
    components so the number is never a black box."""
    eta = a["eta_bars"]
    if eta is None:
        imminence = 0.0                       # moving away, or pace unknown
    else:
        imminence = _clamp((ETA_FAR_BARS - eta) / (ETA_FAR_BARS - ETA_SOON_BARS))

    dist_atr = a["dist_atr"]
    parts = {
        "proximity": _clamp(1.0 - abs(dist_atr) / NEAR_ATR) if dist_atr is not None else 0.0,
        "strength": _clamp((touches - 2) / 3.0),                      # 2 -> 0, 5+ -> 1
        "freshness": _clamp(1.0 - a["bars_since_last"] / FRESH_BARS),
        "cleanliness": _clamp(1.0 - a["traversals"] / 3.0),           # 3 clean breaks -> 0
        "imminence": imminence,
        "participation": _clamp(((a["touch_vol_rel"] or 1.0) - 0.8) / 0.8),
        "room": 1.0 if a["room_atr"] is None else _clamp(a["room_atr"] / 2.0),
    }
    score = sum(parts[k] * w for k, w in SCORE_WEIGHTS.items())
    return {"score": round(score * 100), "parts": {k: round(v, 2) for k, v in parts.items()}}


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


def _last_atr(df: pd.DataFrame) -> float | None:
    a = atr_series(df).iloc[-1]
    return float(a) if a == a else None       # NaN when history is too short


def _median_volume(df: pd.DataFrame) -> float | None:
    if "Volume" not in df:
        return None
    m = float(df["Volume"].median())
    return m or None


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
    atr = _last_atr(df)
    med_volume = _median_volume(df)

    out = []
    for lv in raw:
        attrs = describe_level(df, lv, price, atr, med_volume, raw)
        scored = score_level(attrs, lv["touches"])
        out.append({
            "lo": round(lv["lo"], 2),
            "hi": round(lv["hi"], 2),
            "center": round(lv["level"], 2),
            "touches": lv["touches"],
            "two_sided": lv["two_sided"],
            "first": dates[lv["first_idx"]].strftime("%Y-%m-%d"),
            "last": dates[lv["last_idx"]].strftime("%Y-%m-%d"),
            **attrs,
            **scored,
        })
    out.sort(key=lambda lv: -lv["center"])

    return {"ticker": ticker, "price": round(price, 2),
            "atr": round(atr, 2) if atr else None,
            "atr_pct": round(atr / price * 100.0, 2) if atr and price else None,
            "levels": out, "error": None}


def proximity_scan(tickers: list[str], threshold_pct: float = 2.0,
                   lookback: str = "1y", min_touches: int = MIN_TOUCHES,
                   tolerance: float = CLUSTER_TOL_PCT, span: int = PIVOT_SPAN,
                   threshold_atr: float | None = None):
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
        atr = _last_atr(df)
        med_volume = _median_volume(df)

        for lv in raw:
            attrs = describe_level(df, lv, price, atr, med_volume, raw)
            # "Near" is measured in ATR when asked for, so the same setting
            # means the same thing in a calm market and a fast one. Percent
            # stays the default so existing habits are unchanged.
            if threshold_atr is not None:
                if attrs["dist_atr"] is None or abs(attrs["dist_atr"]) > threshold_atr:
                    continue
            elif abs(attrs["dist_pct"]) > threshold_pct:
                continue
            scored = score_level(attrs, lv["touches"])
            rows.append({
                "ticker": t,
                "price": round(price, 2),
                "level": round(lv["level"], 2),
                "lo": round(lv["lo"], 2),
                "hi": round(lv["hi"], 2),
                "side": "above" if attrs["dist_pct"] >= 0 else "below",
                "touches": lv["touches"],
                "two_sided": lv["two_sided"],
                "first": dates[lv["first_idx"]].strftime("%Y-%m-%d"),
                "last": dates[lv["last_idx"]].strftime("%Y-%m-%d"),
                "atr_pct": round(atr / price * 100.0, 2) if atr and price else None,
                **attrs,
                **scored,
            })

    # Best-ranked first. Distance alone put a stale level the price is drifting
    # away from above a fresh one it is walking into; the score weighs both.
    rows.sort(key=lambda r: (-r["score"], abs(r["dist_pct"])))

    return {"rows": rows, "scanned": scanned,
            "requested": len(tickers), "hits": len(rows)}
