"""
S/R level detection and measurement.

Detection (find_pivots, cluster_levels) came from sr_scanner.py and is still
the part the eye is trained on. It has changed in exactly one respect, for a
reason and with a before/after on real tickers: a *touch* is now one test of
the level rather than one pivot bar. See "Touch counting" below.

Everything after detection only *describes* levels that detection already
found, so the same prices come out carrying more information.

The scoring is built for one seat: a long-only discretionary swing trader who
enters at support rather than waiting for the reaction, stops just below the
structure that formed the level, and wants 2:1 minimum. That is not a neutral
choice and it is why `room` is measured downward as risk rather than upward as
reward, and why R:R carries the largest single weight.

Specified by tests/test_levels_scoring.py. Every assertion there was shown
failing against the previous version before this one was written.
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

# Touch counting. Two pivots four bars apart in the same 1% band are one test
# of the level, not two, and a run of bars with equal highs is one event that
# the old >= comparison marked as a pivot on every bar of the run. Both
# inflated `touches`, which is the largest single influence on the score.
TOUCH_GAP_BARS = 5


def find_pivots(highs: np.ndarray, lows: np.ndarray, span: int = PIVOT_SPAN):
    """Swing highs/lows: a bar that is the extreme within +/- span bars.

    A plateau of equal highs is ONE pivot, at its first bar. The original
    `highs[i] >= window.max()` marked every bar of a tie as its own pivot, so
    a 3-bar plateau arrived at the cluster as three touches. Strict on the
    left and inclusive on the right picks the first bar of the run and
    excludes the rest.

    The last `span` bars still can't confirm a pivot — an unconfirmed pivot
    isn't a level yet.
    """
    pivots = []
    n = len(highs)
    for i in range(span, n - span):
        before_h, after_h = highs[i - span:i], highs[i + 1:i + span + 1]
        before_l, after_l = lows[i - span:i], lows[i + 1:i + span + 1]
        if highs[i] > before_h.max() and highs[i] >= after_h.max():
            pivots.append((i, float(highs[i]), "H"))
        if lows[i] < before_l.min() and lows[i] <= after_l.min():
            pivots.append((i, float(lows[i]), "L"))
    return pivots


def touch_events(idxs, gap: int = TOUCH_GAP_BARS) -> list[list[int]]:
    """Group pivot bar indices into distinct tests of the level.

    Pivots within `gap` bars of each other are the same visit to the band.
    Returns the groups, so callers can count events and still reach the bars.
    """
    groups: list[list[int]] = []
    for i in sorted(set(idxs)):
        if groups and i - groups[-1][-1] <= gap:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def cluster_levels(pivots, tol_pct: float = CLUSTER_TOL_PCT,
                   min_touches: int = MIN_TOUCHES):
    """Greedy price clustering of pivots into levels.

    The clustering itself is unchanged. What changed is `touches`: it counts
    de-clustered touch EVENTS, and `min_touches` therefore filters on events
    too. `pivot_count` keeps the raw number so nothing is lost.
    """
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
        idxs = sorted(p[0] for p in cl)
        events = touch_events(idxs)
        if len(events) < min_touches:
            continue
        prices = [p[1] for p in cl]
        kinds = {p[2] for p in cl}
        levels.append({
            "level": float(np.mean(prices)),
            "lo": float(min(prices)),
            "hi": float(max(prices)),
            "touches": len(events),          # tests of the level, not bars
            "pivot_count": len(cl),          # the raw count, kept
            "first_idx": min(idxs),
            "last_idx": max(idxs),
            "idxs": idxs,                    # every touch bar, for volume/lows
            "event_idxs": [g[0] for g in events],
            "two_sided": ("H" in kinds and "L" in kinds),
        })
    return levels


# ---------------------------------------------------------------------------
# Measurement. Everything below reads OHLCV the scan already downloads; no
# extra requests.

ATR_PERIOD = 14
APPROACH_BARS = 5         # a trading week
FRESH_TAU = 30.0          # convex decay: ~6 trading weeks to 1/e
FRESH_RECENT_BARS = 60    # touches inside this window count toward freshness
EFFICIENCY_BARS = 21      # a trading month, for the chop measure
REACTION_BARS = 10        # how long a bounce gets to develop
MIN_RISK_ATR = 0.10       # floor on the risk leg, or R:R explodes
MAX_RR = 20.0             # cap, so one tiny stop can't own the ranking

# Overhead targets: where profit actually gets taken. The reward leg used
# to be 'the next detected S/R cluster above price', which only
# accidentally catches congestion and is blind to a rejected high or an
# unfilled gap — two of the three things actually traded to.
WICK_FRAC = 0.5           # upper wick at least this much of the bar range
WICK_MIN_ATR = 0.3        # and this deep, or it is noise
GAP_MIN_ATR = 0.25        # smaller than this is not 'semi-major'
CONSOL_BARS = 5           # a run this long counts as congestion...
CONSOL_MAX_ATR = 0.8      # ...if it stays inside this range
MIN_REWARD_ATR = 1.0      # a target nearer than this is not worth a trade


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


def _drift(closes: np.ndarray, window: int = 11) -> tuple[float, bool]:
    """Net drift per bar from a least-squares fit, and whether it is rising.

    NOT mean(|diff|). Mean absolute change is random-walk speed: a name
    oscillating 2% a day and going nowhere scored *faster* than a steady
    trender, which handed the highest imminence to sideways chop — the most
    common reason a top-ranked row gets skipped. A slope cancels the chop and
    gives direction and pace from the same fit.
    """
    seg = np.asarray(closes[-window:], float)
    if len(seg) < 3:
        return 0.0, False
    x = np.arange(len(seg), dtype=float)
    slope = float(np.polyfit(x, seg, 1)[0])
    return abs(slope), slope > 0


def _traversals_since(closes: np.ndarray, lo: float, hi: float,
                      start_idx: int) -> int:
    """Full closes through the BAND, side to side, since the last touch.

    Counting centre crossings scored every live level zero, because
    oscillating inside the band is what a working level looks like. Counting
    from the level's FIRST touch was the other half of the problem: a level
    that broke months ago and has held cleanly since its most recent touch
    read as filthy for breaks that predate its current behaviour.
    """
    side, n = 0, 0
    for c in closes[start_idx:]:
        if c > hi and side <= 0:
            if side < 0:
                n += 1
            side = 1
        elif c < lo and side >= 0:
            if side > 0:
                n += 1
            side = -1
    return n



def overhead_targets(df: pd.DataFrame, price: float, atr: float,
                     all_levels: list[dict]) -> list[dict]:
    """Every structure above `price` that profit could reasonably be taken at.

    Four kinds, pooled and competing:

      sr      a detected S/R cluster
      wick    a failed upper wick — a bar that spiked, closed well below its
              high, and was never exceeded afterward
      gap     an unfilled gap down; the fill target is the pre-gap low
      consol  a run of tight-range bars, targeted at the base of the zone

    Returns [{"price", "kind", "strength"}] sorted by price ascending.
    `strength` is a rough significance in comparable units — wick depth and
    gap size in ATR, consolidation duration in multiples of CONSOL_BARS,
    touches halved for an S/R cluster. Deliberately crude; it only orders the
    optimistic target and is a calibration knob, not a finding.
    """
    if not atr or atr <= 0 or df is None or len(df) < 2:
        return []
    highs = df["High"].to_numpy(float)
    lows = df["Low"].to_numpy(float)
    closes = df["Close"].to_numpy(float)
    n = len(closes)
    out: list[dict] = []

    for lv in all_levels:
        p = float(lv["level"])
        if p > price:
            out.append({"price": p, "kind": "sr",
                        "strength": float(lv.get("touches", 2)) / 2.0})

    # Failed upper wicks. The "never exceeded afterward" test is what makes it
    # standing resistance rather than a spike price walked through later.
    for i in range(n - 1):
        rng = highs[i] - lows[i]
        if rng <= 0:
            continue
        wick = highs[i] - closes[i]
        if wick < WICK_FRAC * rng or wick / atr < WICK_MIN_ATR:
            continue
        if highs[i] <= price:
            continue
        if float(np.max(highs[i + 1:])) >= highs[i]:
            continue
        out.append({"price": float(highs[i]), "kind": "wick",
                    "strength": float(wick / atr)})

    # Unfilled gaps down. Filled means price has traded back through the edge.
    for i in range(1, n):
        if highs[i] >= lows[i - 1]:
            continue
        fill = float(lows[i - 1])
        size = (fill - highs[i]) / atr
        if size < GAP_MIN_ATR or fill <= price:
            continue
        if float(np.max(highs[i:])) >= fill:
            continue
        out.append({"price": fill, "kind": "gap", "strength": float(size)})

    # Consolidation zones: tight windows, merged where they overlap, targeted
    # at the base because that is the near edge a long runs into first.
    zones: list[list[float]] = []
    prev_i = None
    for i in range(n - CONSOL_BARS + 1):
        w_hi = float(np.max(highs[i:i + CONSOL_BARS]))
        w_lo = float(np.min(lows[i:i + CONSOL_BARS]))
        if w_hi - w_lo > CONSOL_MAX_ATR * atr:
            continue
        # Only CONTIGUOUS qualifying windows are the same zone. Merging on
        # "overlaps the previous zone's end" joined a congestion zone to a
        # later, unrelated tight patch and took the minimum low across both,
        # dragging the target down toward price and understating the reward.
        if zones and prev_i is not None and i == prev_i + 1:
            z = zones[-1]
            z[1] = i + CONSOL_BARS
            z[2] = min(z[2], w_lo)
        else:
            zones.append([i, i + CONSOL_BARS, w_lo])
        prev_i = i
    for a, b, base in zones:
        if base > price:
            out.append({"price": float(base), "kind": "consol",
                        "strength": float((b - a) / CONSOL_BARS)})

    out.sort(key=lambda c: c["price"])
    return out


def describe_level(df: pd.DataFrame, lv: dict, price: float, atr: float,
                   med_volume: float, all_levels: list[dict]) -> dict:
    """Measure one level. Plain numbers for the UI to sort on."""
    closes = df["Close"].to_numpy(float)
    highs = df["High"].to_numpy(float)
    lows = df["Low"].to_numpy(float)
    volumes = df["Volume"].to_numpy(float) if "Volume" in df else None
    n = len(closes)
    center, lo, hi = lv["level"], lv["lo"], lv["hi"]
    has_atr = bool(atr and atr > 0)

    dist_pct = (price - center) / center * 100.0
    dist_atr = (price - center) / atr if has_atr else None
    is_support = center < price

    bars_since_last = n - 1 - lv["last_idx"]
    bars_since_first = n - 1 - lv["first_idx"]

    idxs = [i for i in lv.get("idxs", []) if 0 <= i < n]
    recent_touches = sum(1 for i in idxs if (n - 1 - i) <= FRESH_RECENT_BARS)

    # Participation: volume across every touch bar vs this ticker's median.
    touch_vol_rel = None
    if volumes is not None and med_volume and idxs:
        touch_vol_rel = float(np.mean(volumes[idxs]) / med_volume)

    traversals = _traversals_since(closes, lo, hi, lv["last_idx"])
    traversals_ever = _traversals_since(closes, lo, hi, lv["first_idx"])

    # Imminence, from drift rather than random-walk speed. Measured by
    # DIRECTION: price falling straight through a level ends up nearer it while
    # actually leaving it behind, and calling that "approaching" promotes the
    # setups that already happened without you.
    pace, rising = _drift(closes)
    moving_toward = None
    eta_bars = None
    if n > APPROACH_BARS:
        moving_toward = bool((not rising) if is_support else rising)
        if moving_toward and pace > 1e-9:
            eta_bars = round(abs(price - center) / pace, 1)

    # Approach shape. Net displacement over gross travel: 1.0 is a straight
    # line, near 0 is chop. This is "price has been going sideways" as a
    # number, which is the other half of why a top row gets passed over.
    efficiency = None
    if n > EFFICIENCY_BARS:
        seg = closes[-(EFFICIENCY_BARS + 1):]
        gross = float(np.sum(np.abs(np.diff(seg))))
        if gross > 1e-9:
            efficiency = float(abs(seg[-1] - seg[0]) / gross)

    # Long-only geometry. The reward leg is the first level ABOVE price; the
    # risk leg is the structure beneath the level, because the stop goes just
    # below the move that formed it.
    others = sorted(l["level"] for l in all_levels if l["level"] != center)
    floor = next((l for l in reversed(others) if l < center), None)

    # The reward leg, pooled across all four kinds of overhead structure.
    cands = overhead_targets(df, price, atr, all_levels) if is_support else []
    near = next((c for c in cands
                 if has_atr and (c["price"] - center) / atr >= MIN_REWARD_ATR),
                None)
    near_trivial = False
    if near is None and cands:
        # Everything overhead is trivially close. That is a genuinely poor
        # reward, not an unmeasurable one, so it is reported rather than
        # dropped to neutral.
        near = cands[0]
        near_trivial = True
    # The optimistic case is the strongest structure at or beyond the
    # conservative one, so rr_far is never worse than rr_near.
    beyond = [c for c in cands if near is not None
              and c["price"] >= near["price"]]
    far = max(beyond, key=lambda c: c["strength"]) if beyond else None
    target = near["price"] if near else None

    # Back-compatible fields, unchanged meanings, so the existing table keeps
    # telling the truth: nearest level beyond this one, and the one behind it.
    beyond = (next((l for l in others if l > center), None) if not is_support
              else next((l for l in reversed(others) if l < center), None))
    behind = (next((l for l in reversed(others) if l < price), None)
              if not is_support else next((l for l in others if l > price), None))

    def gap_atr(t):
        return None if t is None or not has_atr else round(abs(t - center) / atr, 2)

    # The stop anchor: the low of the structure that formed the level. How far
    # below it the stop actually goes varies with volatility and stays a
    # judgement call, so it is a buffer at the UI, not a constant here.
    # The MOST RECENT touch event, not every touch bar in the lookback. min()
    # across the year picks the deepest wick it can find, which read nine
    # points below a level on RTX and buried a 6-touch level with a 3.17 ATR
    # median bounce at 0.05 on R:R. "A previous significant move" means the
    # structure being leaned on now.
    groups = touch_events(idxs) if idxs else []
    recent_bars = groups[-1] if groups else []
    structural_low = float(np.min(lows[recent_bars])) if recent_bars else None
    structural_high = float(np.max(highs[recent_bars])) if recent_bars else None
    structural_low_ever = float(np.min(lows[idxs])) if idxs else None

    # The stop sits below the BAND, not below the mean of the clustered
    # pivots. A touch that dips into the band without closing under its mean
    # price leaves a low above `center`, which measured from the centre gives
    # a negative risk leg — that read as unmeasurable on 49% of long rows,
    # every one of them then collecting the neutral free pass.
    risk_anchor = None
    if structural_low is not None:
        risk_anchor = min(structural_low, lo)

    risk_atr = None
    risk_unmeasurable = False
    if has_atr and is_support and risk_anchor is not None:
        raw = (center - risk_anchor) / atr
        if raw <= 0:
            risk_unmeasurable = True
        elif raw < MIN_RISK_ATR:
            # A hairline. There is no structure to stop under, so dividing by
            # it manufactures a 300:1 — which is how NFLX reached second in
            # the universe on a 0.036 ATR risk leg. Unmeasurable, not
            # excellent: the score treats it as neither.
            risk_unmeasurable = True
        else:
            risk_atr = round(raw, 2)

    def _reward(c):
        if c is None or not has_atr or not is_support:
            return None
        return round((c["price"] - center) / atr, 2)

    reward_near_atr = _reward(near)
    reward_far_atr = _reward(far)
    reward_atr = reward_near_atr          # back-compatible name

    # No level above price at all is clear air overhead — for a long that is
    # the most reward there is, not the least. An early version of `room`
    # scored the equivalent case as zero, the worst, which is the mistake this
    # avoids deliberately.
    clear_above = bool(is_support and not cands)

    def _rr(reward):
        if reward is None or not risk_atr:
            return None
        return round(min(reward / risk_atr, MAX_RR), 2)

    rr = _rr(reward_near_atr)             # the one the score uses
    rr_far = _rr(reward_far_atr)

    wick_atr = None
    if has_atr and is_support and structural_low is not None:
        wick_atr = round(max(0.0, hi - structural_low) / atr, 2)

    # What actually happened at prior touches. Entering AT the level means
    # there is no confirmation to wait for, so the historical reaction is the
    # only evidence that a buy reaction shows up here at all.
    # Lookahead discipline: a touch needs REACTION_BARS of forward data to
    # have an outcome, and a pivot is not confirmed until PIVOT_SPAN bars
    # later, so only touches at least REACTION_BARS + PIVOT_SPAN old qualify.
    # A bar only counts if its range actually overlapped the band. The pivots
    # that clustered to this price should all satisfy that, but a forward
    # MAXIMUM is not robust to a bar that did not: a name oscillating well
    # above the level reads as a large bounce off a level it never reached.
    # (min() for the structural low is naturally robust; this is not.)
    reactions = []
    if has_atr:
        for i in idxs:
            if n - 1 - i < REACTION_BARS + PIVOT_SPAN:
                continue
            if lows[i] > hi or highs[i] < lo:
                continue
            fwd = closes[i + 1:i + 1 + REACTION_BARS]
            if not len(fwd):
                continue
            move = (float(np.max(fwd)) - closes[i] if is_support
                    else closes[i] - float(np.min(fwd)))
            reactions.append(move / atr)
    reaction_atr = round(float(np.median(reactions)), 2) if reactions else None

    return {
        # --- existing fields, unchanged meanings ---
        "dist_pct": round(dist_pct, 2),
        "dist_atr": round(dist_atr, 2) if dist_atr is not None else None,
        "bars_since_last": int(bars_since_last),
        "bars_since_first": int(bars_since_first),
        "touch_vol_rel": round(touch_vol_rel, 2) if touch_vol_rel else None,
        "traversals": traversals,
        "moving_toward": moving_toward,
        "eta_bars": eta_bars,
        "room_atr": gap_atr(beyond),          # None = nothing beyond
        "behind_atr": gap_atr(behind),
        # --- new ---
        "traversals_ever": traversals_ever,
        "recent_touches": int(recent_touches),
        "band_atr": round((hi - lo) / atr, 2) if has_atr else None,
        "efficiency": round(efficiency, 2) if efficiency is not None else None,
        "structural_low": round(structural_low, 2) if structural_low else None,
        "structural_high": round(structural_high, 2) if structural_high else None,
        "structural_low_ever": (round(structural_low_ever, 2)
                                if structural_low_ever else None),
        "risk_unmeasurable": risk_unmeasurable,
        "risk_anchor": round(risk_anchor, 2) if risk_anchor else None,
        "floor_gap_atr": gap_atr(floor),      # what catches a failed hold
        "clear_below": bool(is_support and floor is None),
        "reward_atr": reward_atr,
        "reward_near_atr": reward_near_atr,
        "reward_far_atr": reward_far_atr,
        "target_near": round(near["price"], 2) if near else None,
        "target_near_kind": near["kind"] if near else None,
        "target_near_trivial": near_trivial,
        "target_far": round(far["price"], 2) if far else None,
        "target_far_kind": far["kind"] if far else None,
        "n_targets": len(cands),
        "risk_atr": risk_atr,
        "rr": rr,
        "rr_far": rr_far,
        "clear_above": clear_above,
        "long_entry": bool(is_support),       # a level above price is not one
        "wick_atr": wick_atr,
        "reaction_atr": reaction_atr,
        "n_reactions": len(reactions),
    }


# Score weights. STILL NOT VALIDATED — these are guesses, like the ones they
# replace. What changed is that they are no longer guesses about components
# that could not discriminate: the previous set declared 0.20 for proximity
# while it contributed a near-constant offset, and 0.12 for cleanliness while
# 89% of real rows scored exactly 0.
#
# The three carrying the most weight are the three that match how the trade is
# actually chosen: R:R against a 2:1 bar, whether the approach is a trend or
# chop, and whether prior touches at this level produced a buy reaction worth
# taking. Components come back with the score so the ranking can be argued
# with, sorted around, or ignored.
SCORE_WEIGHTS = {
    "rr": 0.18,             # reward against the structural stop, 2:1 minimum
    "reaction": 0.14,       # prior touches actually paid
    "efficiency": 0.12,     # arriving on a trend, not chopping sideways
    "strength": 0.10,       # more distinct tests of the level
    "imminence": 0.09,      # heading there, and soon at this drift
    "freshness": 0.08,      # touched recently, and more than once
    "cleanliness": 0.08,    # has not closed clean through it since last touch
    "band": 0.07,           # a tight line you can define risk against
    "proximity": 0.06,      # near enough to matter at all
    "room": 0.04,           # something catches it if the hold fails
    "participation": 0.04,  # touches happened on real volume
}

# Distance scale. The old NEAR_ATR of 6.0 was five times the range the scan
# admits: with a 2-3% threshold and ATR near 2% of price, no row is beyond
# ~1.5 ATR, so proximity measured on a 6-ATR ruler never varied. The scan
# passes its own admission bound in; this is the fallback.
NEAR_ATR = 1.6
ETA_SCALE_BARS = 6.0        # smooth decay; a hard cutoff rebuilt the dead zone
TRAV_SCALE = 4.0            # hyperbolic, so 3 and 28 traversals stay distinct
BAND_MAX_ATR = 1.2          # a band wider than this is a zone, not a line
RR_FLOOR = 1.0              # below 1:1 scores nothing
RR_SPAN = 5.0               # ~6:1 saturates; 2:1 sits low-but-alive
EFFICIENCY_FULL = 0.5       # half the travel in one direction is a clean trend
REACTION_FULL_ATR = 2.0     # a 2 ATR median bounce is as good as it scores
MIN_REACTIONS = 3           # fewer touches than this is not a distribution
CLEAR_ABOVE_RR = 1.0        # clear air overhead = the most reward there is
CLEAR_BELOW_ROOM = 0.3      # nothing catching a failed hold is poor, not zero
NEUTRAL = 0.5               # unmeasurable, so neither rewarded nor punished


def score_level(a: dict, touches: int, near_atr: float = NEAR_ATR) -> dict:
    """Blend the measurements into one sortable 0-100 number, returning the
    components so the number is never a black box.

    Missing measurements score NEUTRAL, never 0. Punishing a level for data
    that could not be computed is how the old `room` ended up ranking clear
    air as the worst case instead of the best.
    """
    eta = a.get("eta_bars")
    imminence = 0.0 if eta is None else 1.0 / (1.0 + eta / ETA_SCALE_BARS)

    dist_atr = a.get("dist_atr")
    scale = near_atr if near_atr and near_atr > 0 else NEAR_ATR

    # Unmeasurable and not-applicable are different cases, and conflating them
    # was a real regression: scoring a resistance level's absent R:R as
    # NEUTRAL handed every level above price half marks on the heaviest
    # component, so rows a long-only trader cannot take outranked real support
    # setups at 1.4:1 and 0.7:1. A level above price has no long entry, so it
    # scores nothing here — which ranks it down without filtering it out.
    rr = a.get("rr")
    if a.get("long_entry") is False:
        rr_part = 0.0
    elif a.get("risk_unmeasurable"):
        rr_part = NEUTRAL          # takes precedence over clear air overhead
    elif a.get("clear_above"):
        rr_part = CLEAR_ABOVE_RR
    elif rr is None:
        rr_part = NEUTRAL
    else:
        rr_part = _clamp((rr - RR_FLOOR) / RR_SPAN)

    # A median wants a distribution behind it. NFLX scored a full reaction on
    # 9.83 ATR from two touches, which is one lucky bounce and one other.
    reaction = a.get("reaction_atr")
    n_react = a.get("n_reactions") or 0
    react_part = (NEUTRAL if reaction is None or n_react < MIN_REACTIONS
                  else _clamp(reaction / REACTION_FULL_ATR))

    eff = a.get("efficiency")
    eff_part = NEUTRAL if eff is None else _clamp(eff / EFFICIENCY_FULL)

    band = a.get("band_atr")
    band_part = NEUTRAL if band is None else _clamp(1.0 - band / BAND_MAX_ATR)

    floor_gap = a.get("floor_gap_atr")
    room_part = (CLEAR_BELOW_ROOM if floor_gap is None
                 else _clamp(floor_gap / 2.0))

    # Freshness decays convexly and counts repeat visits. Linear decay over
    # 120 bars gave a touch from three months ago half credit, and looking
    # only at the most recent touch tied a level tested three times in a
    # fortnight with one tested once.
    recent = a.get("recent_touches") or 1
    freshness = (float(np.exp(-a["bars_since_last"] / FRESH_TAU))
                 * _clamp(0.6 + 0.2 * recent))

    parts = {
        "rr": rr_part,
        "reaction": react_part,
        "efficiency": eff_part,
        "strength": _clamp((touches - 2) / 3.0),          # 2 -> 0, 5+ -> 1
        "imminence": imminence,
        "freshness": freshness,
        "cleanliness": 1.0 / (1.0 + a["traversals"] / TRAV_SCALE),
        "band": band_part,
        "proximity": (_clamp(1.0 - abs(dist_atr) / scale)
                      if dist_atr is not None else 0.0),
        "room": room_part,
        "participation": _clamp(((a.get("touch_vol_rel") or 1.0) - 0.8) / 0.8),
    }
    score = sum(parts[k] * w for k, w in SCORE_WEIGHTS.items())
    return {"score": round(score * 100),
            "parts": {k: round(v, 2) for k, v in parts.items()}}


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


def _near_scale(threshold_pct: float, threshold_atr: float | None,
                atr: float | None, price: float | None) -> float:
    """The distance scale proximity is measured on: whatever the scan admits.

    Hardcoding it is what made proximity a constant. In ATR mode the bound is
    given directly; in percent mode it converts through this ticker's ATR, so
    the same 2% means a different number of ATR in a calm name and a fast one.
    """
    if threshold_atr is not None and threshold_atr > 0:
        return float(threshold_atr)
    if atr and price and atr > 0:
        return max(threshold_pct / 100.0 * price / atr, 0.25)
    return NEAR_ATR


def level_map(ticker: str, lookback: str = "1y", min_touches: int = MIN_TOUCHES,
              tolerance: float = CLUSTER_TOL_PCT, span: int = PIVOT_SPAN):
    """Every qualifying level for one ticker, structured for the UI ladder."""
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
    near = _near_scale(2.0, None, atr, price)

    out = []
    for lv in raw:
        attrs = describe_level(df, lv, price, atr, med_volume, raw)
        scored = score_level(attrs, lv["touches"], near)
        out.append({
            "lo": round(lv["lo"], 2),
            "hi": round(lv["hi"], 2),
            "center": round(lv["level"], 2),
            "touches": lv["touches"],
            "pivot_count": lv["pivot_count"],
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
    """Across a universe of tickers, every level within the threshold of the
    current price — the morning scan from sr_scanner.py's default mode.

    Returns flat rows, one per (ticker, near-level), best-ranked first. Each
    row carries enough to render and to click through to the full ladder.
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
        near = _near_scale(threshold_pct, threshold_atr, atr, price)

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
            scored = score_level(attrs, lv["touches"], near)
            rows.append({
                "ticker": t,
                "price": round(price, 2),
                "level": round(lv["level"], 2),
                "lo": round(lv["lo"], 2),
                "hi": round(lv["hi"], 2),
                "side": "above" if attrs["dist_pct"] >= 0 else "below",
                "touches": lv["touches"],
                "pivot_count": lv["pivot_count"],
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
