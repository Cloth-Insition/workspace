"""
Levels scoring diagnostics: every defect found in the score, as a test that
asserts the CORRECT behaviour and therefore FAILS against the current code.

This file is written deliberately red. Per the repo rule, a regression test
is only trustworthy once it has been shown to fail against the buggy code;
these were all confirmed failing before any fix was written. A fix for the
scoring redesign turns them green one at a time, and any that stays red is
a part of the redesign that has not actually landed.

Offline and deterministic: synthetic OHLCV, no yfinance, no credentials,
no network. Detection (find_pivots / cluster_levels) is exercised only where
a defect is IN detection's touch counting; the level maths itself is not
under test and is not to be changed.

Scored for a long-only swing trader who enters at support with a stop below
the structure that formed the level, and who wants 2:1 minimum. That is the
user of this scanner; several checks below only make sense from that seat.

    python tests/test_levels_scoring.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src-python"))

import numpy as np
import pandas as pd

from engine.levels import (
    cluster_levels,
    describe_level,
    find_pivots,
    overhead_targets,
    score_level,
)

ATR = 2.0          # every fixture below is priced around 100 with ATR 2.0
MED_VOL = 1_000_000

_results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    _results.append((name, bool(passed), detail))


# --------------------------------------------------------------- fixtures

def make_df(closes, highs=None, lows=None, volumes=None) -> pd.DataFrame:
    """Synthetic daily OHLCV. Highs/lows default to a tight envelope so the
    close path is what drives every measurement."""
    n = len(closes)
    c = np.array(closes, float)
    h = np.array(highs, float) if highs is not None else c + 0.1
    lo = np.array(lows, float) if lows is not None else c - 0.1
    v = np.array(volumes, float) if volumes is not None else np.full(n, MED_VOL)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"High": h, "Low": lo, "Close": c, "Volume": v},
                        index=idx)


def make_level(center: float, band: float = 0.2, touches: int = 4,
               first_idx: int = 0, last_idx: int = 40, idxs=None) -> dict:
    return {
        "level": center,
        "lo": center - band / 2.0,
        "hi": center + band / 2.0,
        "touches": touches,
        "first_idx": first_idx,
        "last_idx": last_idx,
        "idxs": idxs if idxs is not None else [first_idx, last_idx],
        "two_sided": True,
    }


def trend_closes(start: float, end: float, n: int = 60):
    """Smooth drift. Pace (mean abs diff) equals the per-bar drift exactly,
    which is the honest case for a trending approach."""
    return list(np.linspace(start, end, n))


def noisy_closes(start: float, end: float, n: int = 60, amp: float = 1.0):
    """Drift plus realistic bar-to-bar noise, deterministic (no RNG). The
    noise dominates mean-abs-diff, which is exactly how real pace behaves."""
    base = np.linspace(start, end, n)
    wig = amp * np.array([1.0 if i % 2 == 0 else -1.0 for i in range(n)])
    return list(base + wig)


def approach_with_touches(center: float, idxs, n: int = 60,
                          end: float | None = None, recovery: float = 4.0,
                          wick: float = 1.0, wicks=None):
    """A coherent support fixture: price actually dips INTO the band at each
    touch index and bounces away, ending above the level.

    Needed because a fixture whose touch bars never visit the level makes the
    risk leg (level minus structural low) negative, which silently zeroes any
    R:R assertion built on it. The oracle caught exactly that.

    Returns (df, idxs).
    """
    end = center + 2.0 if end is None else end
    xs: list[float] = [0]
    ys: list[float] = [center + recovery]
    for i in idxs:
        xs.append(i)
        ys.append(center + 0.05)          # closes just inside the band
        xs.append(min(i + 5, n - 2))      # bounces away over the next week
        ys.append(center + recovery)
    xs.append(n - 1)
    ys.append(end)
    # np.interp needs strictly increasing x; keep the last value at ties.
    seen: dict[float, float] = {}
    for x, y in zip(xs, ys):
        seen[x] = y
    ax = sorted(seen)
    closes = np.interp(np.arange(n), ax, [seen[x] for x in ax])

    lows = closes - 0.1
    for k, i in enumerate(idxs):
        # `wicks` gives each touch its own depth, for testing which touch
        # the risk leg is taken from.
        d = wick if wicks is None else wicks[k]
        lows[i] = center - d              # the wick that defines the stop
    return make_df(list(closes), lows=list(lows)), list(idxs)


def with_overhead(center: float = 100.0, price: float = 102.0, n: int = 80,
                  touch_idxs=(60, 68, 74)):
    """A support level at `center` with three kinds of overhead structure.

    Laid out newest-lowest so each structure is genuinely unbroken by what
    came after it, which is what makes it still act as resistance:

      bars 0-14   drifting around 113-115
      bar 15      GAP DOWN -- low[14]=112.0 over high[15]=107.0, never refilled
                  (fill target 112.0 = 6.0 ATR above the level)
      bar 25      FAILED UPPER WICK -- high 107.5, close 103.0, never exceeded
                  (target 107.5 = 3.75 ATR above the level)
      bars 40-50  CONSOLIDATION in 104.0-104.8
                  (base 104.0 = 2.0 ATR above the level)
      bars 55+    decline into the level, touching it at `touch_idxs`
    """
    closes = np.full(n, 113.0)
    highs = np.full(n, 114.0)
    lows = np.full(n, 112.0)

    # bar 15: gap down. Nothing afterwards trades back up through 112.0.
    for i in range(15, n):
        closes[i], highs[i], lows[i] = 106.0, 107.0, 105.0

    # bar 25: the failed upper wick.
    highs[25], closes[25], lows[25] = 107.5, 103.0, 102.5

    for i in range(26, n):
        closes[i], highs[i], lows[i] = 105.0, 105.5, 104.5

    # bars 40-50: tight consolidation, base 104.0.
    for i in range(40, 51):
        closes[i], highs[i], lows[i] = 104.4, 104.8, 104.0

    # bars 55 onward: decline into the level and end at `price`.
    tail = np.linspace(104.0, price, n - 55)
    for k, i in enumerate(range(55, n)):
        closes[i], highs[i], lows[i] = tail[k], tail[k] + 0.2, tail[k] - 0.2

    for i in touch_idxs:                      # dip into the band and recover
        closes[i], lows[i], highs[i] = center + 0.05, center - 0.6, center + 0.5

    return (make_df(list(closes), highs=list(highs), lows=list(lows)),
            list(touch_idxs))


def bare_attrs(**over) -> dict:
    """A minimal describe_level-shaped dict, for scoring maths in isolation."""
    a = {"dist_atr": -0.5, "bars_since_last": 5, "touch_vol_rel": 1.0,
         "traversals": 0, "eta_bars": 5.0, "moving_toward": True,
         "room_atr": 1.0, "behind_atr": 1.0}
    a.update(over)
    return a


# ------------------------------------------------- 1. touch-count inflation

def test_plateau_ties_are_one_touch() -> None:
    """A run of bars with equal highs is ONE test of the level. find_pivots
    uses >= / <=, so every bar in the plateau is marked a pivot and the
    cluster counts them all as separate touches."""
    highs = np.array([1, 2, 3, 5, 5, 5, 3, 2, 1, 2, 3], float)
    pivots = find_pivots(highs, highs - 1.0, span=3)
    highs_only = [p for p in pivots if p[2] == "H"]
    check("plateau ties count as one touch",
          len(highs_only) == 1,
          "a 3-bar equal-high plateau produced %d pivots at %s; one event "
          "should be one touch" % (len(highs_only), [p[0] for p in highs_only]))


def test_adjacent_pivots_are_one_touch() -> None:
    """Two pivots four bars apart in the same 1%% band are one test of the
    level, not two. With span 3 they both confirm, and touches counts 2."""
    highs = np.array([90, 91, 92, 93, 94, 100, 95, 94, 95, 100,
                      94, 93, 92, 91, 90, 89, 88, 87, 86, 85], float)
    pivots = find_pivots(highs, highs - 1.0, span=3)
    levels = cluster_levels([p for p in pivots if p[2] == "H"],
                            tol_pct=1.0, min_touches=1)
    near = [lv for lv in levels if abs(lv["level"] - 100.0) < 1.0]
    got = near[0]["touches"] if near else 0
    check("pivots 4 bars apart count as one touch",
          got == 1,
          "two peaks 4 bars apart in one band counted as %d touches; touch "
          "count should be de-clustered in time" % got)


# ------------------------------------------------------- 2. dead components

def test_proximity_discriminates_inside_admission_range() -> None:
    """NEAR_ATR is 6.0 but the scan only admits rows inside roughly 1.5 ATR,
    so proximity is measured on a ruler five times too long and contributes
    a near-constant offset to every row."""
    p_near = score_level(bare_attrs(dist_atr=-0.1), 4)["parts"]["proximity"]
    p_far = score_level(bare_attrs(dist_atr=-1.5), 4)["parts"]["proximity"]
    spread = p_near - p_far
    check("proximity spans its admission range",
          spread >= 0.5,
          "proximity only spans %.3f between 0.1 and 1.5 ATR (%.3f to %.3f); "
          "a scored component needs range where the rows actually live"
          % (spread, p_far, p_near))


def test_cleanliness_distinguishes_three_from_many_traversals() -> None:
    """1 - traversals/3 floors at zero, so a level crossed 3 times and one
    crossed 28 times are identical. Observed traversals run to 28."""
    ca = score_level(bare_attrs(traversals=3), 4)["parts"]["cleanliness"]
    cb = score_level(bare_attrs(traversals=28), 4)["parts"]["cleanliness"]
    check("cleanliness separates 3 from 28 traversals",
          ca > cb,
          "3 traversals scored %.2f and 28 scored %.2f; the normaliser "
          "saturates about 5x too early" % (ca, cb))


def test_traversals_measured_since_last_touch() -> None:
    """Traversals are counted from the level's FIRST touch, so breaks from
    months ago still condemn a level that has held cleanly since its most
    recent touch."""
    early = [103, 97, 103, 97, 103, 97, 103, 97] * 5   # 40 bars of crossings
    after = [102.0 + 0.05 * i for i in range(20)]      # clean hold, no crosses
    df = make_df(early + after)
    lv = make_level(100.0, band=0.2, first_idx=0, last_idx=40)
    a = describe_level(df, lv, float(df["Close"].iloc[-1]), ATR, MED_VOL, [])
    check("traversals counted since last touch",
          a["traversals"] <= 1,
          "a level that has held cleanly since its last touch reported %d "
          "traversals, all of them from before it" % a["traversals"])


def test_imminence_is_graded_not_binary() -> None:
    """With realistic bar-to-bar noise, pace (mean ABS change) is large, so
    every admitted distance divides down to 'arriving now'. Observed: 53% of
    rows exactly 0, 44% exactly 1, almost nothing between."""
    df = make_df(noisy_closes(106, 102, amp=1.0))
    price = float(df["Close"].iloc[-1])
    vals = set()
    for d_atr in (0.2, 0.5, 0.8, 1.1, 1.4):
        lv = make_level(price - d_atr * ATR)
        a = describe_level(df, lv, price, ATR, MED_VOL, [])
        vals.add(round(score_level(a, 4)["parts"]["imminence"], 2))
    check("imminence is graded across admitted distances",
          len(vals) >= 4,
          "five distances 0.2-1.4 ATR produced %d distinct imminence "
          "value(s): %s" % (len(vals), sorted(vals)))


# --------------------------------------------------- 3. chop, the top skip

def test_steady_approach_outranks_sideways_chop() -> None:
    """The headline defect. Chopping sideways is the most common reason a top
    row gets skipped, and pace = mean(|diff|) is random-walk speed, not
    drift -- so a chopping name gets a SHORTER eta and a HIGHER score than a
    name walking steadily into the same level from the same distance."""
    level = make_level(100.0, band=0.2, last_idx=50)

    trend = make_df(trend_closes(116, 102, n=60))
    a_trend = describe_level(trend, level, 102.0, ATR, MED_VOL, [])
    s_trend = score_level(a_trend, 4)

    # Same endpoint, same distance, but oscillating 101-107 and going nowhere.
    chop_path = [101.0 if i % 2 == 0 else 107.0 for i in range(54)]
    chop_path += [107.0, 106.0, 105.0, 104.0, 103.0, 102.0]
    chop = make_df(chop_path)
    a_chop = describe_level(chop, level, 102.0, ATR, MED_VOL, [])
    s_chop = score_level(a_chop, 4)

    check("steady approach beats sideways chop on imminence",
          s_trend["parts"]["imminence"] >= s_chop["parts"]["imminence"],
          "chop imminence %.2f vs trend %.2f (eta %s vs %s bars)"
          % (s_chop["parts"]["imminence"], s_trend["parts"]["imminence"],
             a_chop["eta_bars"], a_trend["eta_bars"]))

    check("steady approach beats sideways chop on total score",
          s_trend["score"] >= s_chop["score"],
          "chop scored %d and the steady approach %d from the same distance "
          "to the same level" % (s_chop["score"], s_trend["score"]))


def test_chop_is_measured_at_all() -> None:
    """There is no measurement of how directionally efficient the approach
    was, which is the thing being eyeballed when a row is skipped."""
    df = make_df([101.0 if i % 2 == 0 else 107.0 for i in range(60)])
    a = describe_level(df, make_level(100.0), 101.0, ATR, MED_VOL, [])
    check("an efficiency/chop measure exists",
          any(k in a for k in ("efficiency", "chop", "approach_efficiency")),
          "describe_level returns no efficiency measure; keys are %s"
          % sorted(a.keys()))


# ----------------------------------------- 4. long-only risk/reward geometry

def test_room_does_not_reward_air_under_support() -> None:
    """For a support level, `beyond` resolves DOWNWARD, so room_atr measures
    empty space beneath the level -- and clear air (None) scores 1.0, the
    maximum. For a long entering at support with a stop below, air underneath
    is the failure case, not the reward."""
    df = make_df(trend_closes(106, 102))
    price = 102.0
    support = make_level(100.0)

    floor_below = [support, make_level(98.0), make_level(104.0)]
    clear_air = [support, make_level(104.0)]

    a_floor = describe_level(df, support, price, ATR, MED_VOL, floor_below)
    a_air = describe_level(df, support, price, ATR, MED_VOL, clear_air)
    r_floor = score_level(a_floor, 4)["parts"]["room"]
    r_air = score_level(a_air, 4)["parts"]["room"]

    check("support with a floor beneath is not scored worse than clear air",
          r_floor >= r_air,
          "clear air below support scored room %.2f but a level 1 ATR "
          "beneath scored %.2f; for a long-only entry the ranking is "
          "inverted" % (r_air, r_floor))


def test_reward_leg_affects_the_score() -> None:
    """The distance up to the first level above price is the reward leg of the
    trade. It is computed, stored as `behind_atr`, and carries no weight."""
    df, idxs = approach_with_touches(100.0, [10, 20, 30, 40])
    price = float(df["Close"].iloc[-1])
    support = make_level(100.0, last_idx=40, idxs=idxs)

    tight = [support, make_level(102.5)]     # target 1.25 ATR above support
    generous = [support, make_level(110.0)]  # target 5.0 ATR above support

    a_tight = describe_level(df, support, price, ATR, MED_VOL, tight)
    a_gen = describe_level(df, support, price, ATR, MED_VOL, generous)
    s_tight = score_level(a_tight, 4)["score"]
    s_gen = score_level(a_gen, 4)["score"]

    check("a further target scores better than a nearby one",
          s_gen > s_tight,
          "target %s ATR away scored %d and target %s ATR away scored %d; "
          "the reward leg is unscored"
          % (a_gen["behind_atr"], s_gen, a_tight["behind_atr"], s_tight))


def test_resistance_does_not_get_a_free_pass_on_rr() -> None:
    """A level ABOVE price is not a long entry, so it has no R:R to measure.
    Scoring that as NEUTRAL hands every resistance row half marks on the
    heaviest component while support rows have to earn it -- which promotes
    exactly the rows a long-only trader cannot take.

    Missing-because-unmeasurable and missing-because-not-applicable are
    different cases. This is the second one.
    """
    df, idxs = approach_with_touches(100.0, [10, 20, 30, 40])
    level = make_level(100.0, last_idx=40, idxs=idxs)

    # The support case must have a POOR but real R:R -- a target barely above
    # the level. Comparing against a good R:R makes the assertion vacuous,
    # because a free 0.5 loses to a genuinely good ratio anyway. The live
    # failure was resistance outranking support rows at 1.41:1 and 0.71:1.
    # The target must sit above PRICE, not merely above the level, or it
    # is not a target at all and the row scores as clear air overhead.
    poor = [level, make_level(102.3)]        # reward 1.15 ATR on 0.5 ATR risk
    a_sup = describe_level(df, level, 102.0, ATR, MED_VOL, poor)
    a_res = describe_level(df, level, 98.0, ATR, MED_VOL,
                           [level, make_level(104.0)])
    p_sup = score_level(a_sup, 4)["parts"]["rr"]
    p_res = score_level(a_res, 4)["parts"]["rr"]

    check("resistance scores no better than poor-R:R support",
          p_res <= p_sup,
          "resistance (no long entry, rr unmeasurable) scored rr %.2f while "
          "support at a real %s:1 scored %.2f"
          % (p_res, a_sup["rr"], p_sup))


def test_risk_reward_is_reported() -> None:
    """2:1 minimum is the stated bar. Nothing in the output expresses it."""
    df, idxs = approach_with_touches(100.0, [10, 20, 30, 40])
    support = make_level(100.0, last_idx=40, idxs=idxs)
    a = describe_level(df, support, float(df["Close"].iloc[-1]), ATR, MED_VOL,
                       [support, make_level(108.0)])
    check("an R-multiple is reported",
          any(k in a for k in ("rr", "r_multiple", "risk_reward")),
          "describe_level reports no R:R; keys are %s" % sorted(a.keys()))


def test_structural_low_is_reported() -> None:
    """The stop goes just below the structure that formed the level, so the
    risk leg is the low of the touch bars -- derivable from idxs, which
    cluster_levels already stores."""
    df, idxs = approach_with_touches(100.0, [10, 20, 30, 40], wick=1.0)
    lv = make_level(100.0, last_idx=40, idxs=idxs)
    a = describe_level(df, lv, float(df["Close"].iloc[-1]), ATR, MED_VOL, [])
    check("a structural low is reported",
          any(k in a for k in ("structural_low", "stop_low", "touch_low")),
          "no structural low for the risk leg; keys are %s" % sorted(a.keys()))


# ------------------------------------------- 5. what happened at the touches

def test_reaction_size_is_reported() -> None:
    """Entering AT the level means the historical reaction distribution is
    the only confirmation available. Nothing measures how far price travelled
    in your favour after prior touches."""
    # Each touch bounces ~2 ATR over the following week: a level that pays.
    df, idxs = approach_with_touches(100.0, [10, 20, 30, 40], recovery=4.0)
    lv = make_level(100.0, last_idx=40, idxs=idxs)
    a = describe_level(df, lv, float(df["Close"].iloc[-1]), ATR, MED_VOL, [])
    check("reaction size after prior touches is reported",
          any(k in a for k in ("reaction_atr", "median_reaction", "bounce_atr")),
          "no post-touch reaction measure; keys are %s" % sorted(a.keys()))


def test_reaction_size_separates_paying_from_dead_levels() -> None:
    """The measurement has to carry signal, not merely exist. A level whose
    touches each produced a 2 ATR bounce and one whose touches produced 0.2
    ATR must not look the same -- that difference is the whole basis for
    entering AT the level rather than waiting for confirmation.

    Both fixtures have identical touch counts, freshness and band width, so
    only the historical reaction differs.
    """
    pays, idxs = approach_with_touches(100.0, [10, 20, 30, 40], recovery=4.0)
    dead, _ = approach_with_touches(100.0, [10, 20, 30, 40], recovery=0.4)
    lv = make_level(100.0, last_idx=40, idxs=idxs)

    a_pays = describe_level(pays, lv, float(pays["Close"].iloc[-1]), ATR,
                            MED_VOL, [])
    a_dead = describe_level(dead, lv, float(dead["Close"].iloc[-1]), ATR,
                            MED_VOL, [])
    key = next((k for k in ("reaction_atr", "median_reaction", "bounce_atr")
                if k in a_pays), None)
    if key is None:
        check("reaction size separates paying from dead levels", False,
              "no reaction measure exists, so it cannot discriminate")
        return
    check("reaction size separates paying from dead levels",
          a_pays[key] > a_dead[key] * 2.0,
          "paying level %.2f vs dead level %.2f" % (a_pays[key], a_dead[key]))


def test_hairline_risk_leg_is_not_a_great_trade() -> None:
    """A touch that barely dipped below the level gives a risk leg under
    MIN_RISK_ATR. Flooring it and dividing turns "no structure to stop under"
    into a 300:1 reward ratio, which then saturates the heaviest component.

    Unmeasurable is not excellent. It scores NEUTRAL at most. Seen live on
    NFLX: structural low 0.036 ATR under the level, rr capped at 20, ranked
    second in the whole universe.
    """
    df, idxs = approach_with_touches(100.0, [10, 20, 30, 40], wick=0.04)
    level = make_level(100.0, band=0.1, last_idx=40, idxs=idxs)
    a = describe_level(df, level, 102.0, ATR, MED_VOL,
                       [level, make_level(115.0)])
    part = score_level(a, 4)["parts"]["rr"]
    check("a hairline risk leg does not score top marks on R:R",
          part <= 0.5,
          "risk leg %s ATR gave rr %s and scored %.2f"
          % (a["risk_atr"], a["rr"], part))


def test_risk_leg_uses_the_most_recent_structure() -> None:
    """The stop goes below the structure that formed the level -- a previous
    significant move, meaning a recent one. Taking min() across every touch
    bar in the lookback picks the deepest wick of the year instead, which
    inflates the risk leg and buries the rows that best fit the criteria.

    Seen live on RTX: structural low nine points under a level at 193.38, so
    a 6-touch level with a 3.17 ATR median bounce scored 0.05 on R:R.
    """
    # An old deep wick, then three shallow recent touches.
    df, idxs = approach_with_touches(100.0, [10, 20, 30, 40],
                                     wicks=[4.5, 0.6, 0.5, 0.55])
    level = make_level(100.0, last_idx=40, idxs=idxs)
    a = describe_level(df, level, 102.0, ATR, MED_VOL,
                       [level, make_level(106.0)])
    # Recent structure sits ~0.55 below the level = ~0.28 ATR, not 4.5 = 2.25.
    check("the risk leg comes from recent structure, not the year's worst wick",
          a["risk_atr"] is not None and a["risk_atr"] < 0.6,
          "risk leg read %s ATR; the recent touches are ~0.28 ATR below the "
          "level and the 4.5-point wick is %d bars old"
          % (a["risk_atr"], 60 - 1 - 10))


def test_reaction_needs_enough_touches_to_median() -> None:
    """A median over two samples is not a distribution. NFLX scored a full
    reaction on 9.83 ATR from two touches."""
    df, idxs = approach_with_touches(100.0, [20, 40], recovery=8.0)
    level = make_level(100.0, last_idx=40, idxs=idxs)
    a = describe_level(df, level, 102.0, ATR, MED_VOL, [])
    part = score_level(a, 4)["parts"]["reaction"]
    check("two touches do not earn a full reaction score",
          part <= 0.5,
          "reaction %s ATR over %d touches scored %.2f"
          % (a["reaction_atr"], a["n_reactions"], part))


def test_risk_leg_survives_a_shallow_recent_touch() -> None:
    """A touch that dips into the band but not below its mean price must still
    have a measurable risk leg. Measuring from the band CENTRE against a low
    that sits above it yields a negative number, read as unmeasurable, and
    that fired on 49% of long rows live -- every one collecting the NEUTRAL
    free pass on the heaviest component.

    The stop goes below the band, not below the mean of the clustered pivots.
    """
    # Recent touch dips only 0.05 into a 0.6-wide band: low is above centre.
    df, idxs = approach_with_touches(100.0, [10, 20, 30, 40],
                                     wicks=[0.5, 0.4, 0.4, -0.25])
    level = make_level(100.0, band=0.6, last_idx=40, idxs=idxs)
    a = describe_level(df, level, 102.0, ATR, MED_VOL,
                       [level, make_level(106.0)])
    check("a shallow recent touch still yields a risk leg",
          a["risk_atr"] is not None and not a["risk_unmeasurable"],
          "structural low %s sits above the band centre %.2f, so risk read "
          "%s (unmeasurable=%s); the band low at %.2f is the anchor"
          % (a["structural_low"], level["level"], a["risk_atr"],
             a["risk_unmeasurable"], level["lo"]))


def test_wick_rejection_depth_is_reported() -> None:
    """'A cluster of wicks' is the structure being leaned on. Lower-wick
    depth at the touch bars is the long-only form of rejection quality."""
    # Deep lower wicks through the band at every touch, closing back inside.
    df, idxs = approach_with_touches(100.0, [10, 20, 30, 40], wick=1.6)
    lv = make_level(100.0, last_idx=40, idxs=idxs)
    a = describe_level(df, lv, float(df["Close"].iloc[-1]), ATR, MED_VOL, [])
    check("wick rejection depth is reported",
          any(k in a for k in ("wick_atr", "rejection_atr", "penetration_atr")),
          "deep lower wicks at every touch are not measured; keys are %s"
          % sorted(a.keys()))


# ------------------------------------------------------ 6. unused variation

def test_band_width_affects_the_score() -> None:
    """Band width in ATR ranges 0.03 to 1.14 across a real scan (median
    0.43) and is scored nowhere. It is 'how cleanly is this line drawn'."""
    # Both bands must clear MIN_RISK_ATR, or the "tight" one routes through
    # the hairline/unmeasurable path and this stops being a test of band
    # width. Real levels do get tighter than that (V came in at 0.09 ATR);
    # scoring those as unmeasurable is correct, just not what this asserts.
    # Both need a target above price too, so neither takes the clear-air path.
    df, idxs = approach_with_touches(100.0, [10, 20, 30, 40], wick=0.6)
    price = float(df["Close"].iloc[-1])
    target = make_level(106.0)
    a_t = describe_level(df, make_level(100.0, band=0.50, last_idx=40,
                                        idxs=idxs), price, ATR,
                         MED_VOL, [target])
    a_l = describe_level(df, make_level(100.0, band=2.20, last_idx=40,
                                        idxs=idxs), price, ATR,
                         MED_VOL, [target])
    s_t = score_level(a_t, 4)["score"]
    s_l = score_level(a_l, 4)["score"]
    check("a tight band scores better than a wide one",
          s_t > s_l,
          "0.25 ATR band scored %d and 1.10 ATR band scored %d" % (s_t, s_l))


def test_freshness_counts_repeat_recent_touches() -> None:
    """bars_since_last looks only at the most recent touch, so a level tested
    three times in the last fortnight ties with one tested once."""
    df = make_df(trend_closes(106, 102))
    price = 102.0
    many = make_level(100.0, last_idx=45, idxs=[45, 50, 55])
    once = make_level(100.0, last_idx=45, idxs=[45])
    f_many = score_level(describe_level(df, many, price, ATR, MED_VOL, []),
                         3)["parts"]["freshness"]
    f_once = score_level(describe_level(df, once, price, ATR, MED_VOL, []),
                         3)["parts"]["freshness"]
    check("repeat recent touches beat a single one on freshness",
          f_many > f_once,
          "3 recent touches scored freshness %.2f and 1 scored %.2f"
          % (f_many, f_once))


def test_freshness_decay_is_convex() -> None:
    """Linear decay over 120 bars gives a touch from 3 months ago half
    credit. For a swing trader a fortnight-old touch is far more live than
    a 60-bar-old one, which linear decay cannot express."""
    def fresh(bars: int) -> float:
        return score_level(bare_attrs(bars_since_last=bars),
                           4)["parts"]["freshness"]
    near_drop = fresh(5) - fresh(20)      # a fortnight of ageing, recent
    far_drop = fresh(80) - fresh(95)      # the same ageing, long ago
    check("freshness decays faster when recent",
          near_drop > far_drop * 1.5,
          "ageing 15 bars costs %.3f when recent and %.3f when old; decay is "
          "linear, not convex" % (near_drop, far_drop))


# -------------------------------------------- 7. the reward leg he trades to

def _expected_rr_part(rr) -> float:
    from engine.levels import RR_FLOOR, RR_SPAN
    if rr is None:
        return 0.5
    return max(0.0, min(1.0, (rr - RR_FLOOR) / RR_SPAN))


def test_failed_upper_wick_is_a_target() -> None:
    """A bar that spiked up, closed well below its high, and was never
    exceeded afterward is standing overhead resistance. Nothing found it: the
    reward leg only ever looked at detected S/R clusters."""
    df, _ = with_overhead()
    cands = overhead_targets(df, 102.0, ATR, [])
    wicks = [c for c in cands if c["kind"] == "wick"]
    check("a failed upper wick is found as a target",
          any(abs(c["price"] - 107.5) < 0.3 for c in wicks),
          "wick targets found: %s" % [round(c["price"], 2) for c in wicks])


def test_unfilled_gap_is_a_target() -> None:
    """A gap down that price has not traded back through is a fill target."""
    df, _ = with_overhead()
    gaps = [c for c in overhead_targets(df, 102.0, ATR, [])
            if c["kind"] == "gap"]
    check("an unfilled gap is found as a target",
          any(abs(c["price"] - 112.0) < 0.5 for c in gaps),
          "gap targets found: %s" % [round(c["price"], 2) for c in gaps])


def test_filled_gap_is_not_a_target() -> None:
    """Once price has traded back through it the gap is spent."""
    df, _ = with_overhead()
    closes = list(df["Close"].to_numpy(float))
    highs = list(df["High"].to_numpy(float))
    lows = list(df["Low"].to_numpy(float))
    highs[30], closes[30] = 113.0, 112.5      # trades up through the fill
    filled = make_df(closes, highs=highs, lows=lows)
    gaps = [c for c in overhead_targets(filled, 102.0, ATR, [])
            if c["kind"] == "gap"]
    check("a filled gap is not a target",
          not any(abs(c["price"] - 112.0) < 0.5 for c in gaps),
          "gap targets after the fill: %s"
          % [round(c["price"], 2) for c in gaps])


def test_consolidation_zone_is_a_target() -> None:
    """A run of tight-range bars overhead is the third thing he targets."""
    df, _ = with_overhead()
    cons = [c for c in overhead_targets(df, 102.0, ATR, [])
            if c["kind"] == "consol"]
    # Tight tolerance on purpose: a 0.6 window also admits the 103.47 patch
    # from the declining tail, which let a merge bug through once already.
    check("a consolidation zone is found as a target",
          any(abs(c["price"] - 104.0) < 0.2 for c in cons),
          "consolidation targets found: %s"
          % [round(c["price"], 2) for c in cons])


def test_sr_levels_remain_in_the_target_pool() -> None:
    """All four kinds pool: detected S/R above price still competes."""
    cands = overhead_targets(with_overhead()[0], 102.0, ATR,
                             [make_level(106.0)])
    check("S/R clusters stay in the target pool",
          any(c["kind"] == "sr" and abs(c["price"] - 106.0) < 0.3
              for c in cands),
          "kinds found: %s" % sorted({c["kind"] for c in cands}))


def test_near_target_skips_a_trivial_one() -> None:
    """rr_near takes the nearest target that still leaves a worthwhile move,
    not the nearest obstacle of any size."""
    df, idxs = with_overhead(price=100.5)
    level = make_level(100.0, band=0.4, last_idx=idxs[-1], idxs=idxs)
    # A target 0.5 ATR above the level is not worth a trade; 104.0 is.
    a = describe_level(df, level, 100.5, ATR, MED_VOL,
                       [level, make_level(101.0)])
    check("the near target skips a trivial one",
          a["reward_near_atr"] is not None and a["reward_near_atr"] >= 1.0,
          "near reward %s ATR at %s (%s); a 101.0 target would be 0.5 ATR"
          % (a["reward_near_atr"], a["target_near"], a["target_near_kind"]))


def test_far_target_is_the_strongest_not_the_nearest() -> None:
    """rr_far reports the strongest overhead structure regardless of distance,
    so the optimistic case is visible alongside the conservative one."""
    df, idxs = with_overhead()
    level = make_level(100.0, band=0.4, last_idx=idxs[-1], idxs=idxs)
    a = describe_level(df, level, 102.0, ATR, MED_VOL, [level])
    ok = (a["reward_far_atr"] is not None and a["reward_near_atr"] is not None
          and a["reward_far_atr"] > a["reward_near_atr"])
    check("the far target is further than the near one", ok,
          "near %s ATR (%s at %s), far %s ATR (%s at %s)"
          % (a["reward_near_atr"], a["target_near_kind"], a["target_near"],
             a["reward_far_atr"], a["target_far_kind"], a["target_far"]))


def test_score_uses_the_conservative_rr() -> None:
    """Both are reported; the ranking is scored on rr_near."""
    df, idxs = with_overhead()
    level = make_level(100.0, band=0.4, last_idx=idxs[-1], idxs=idxs)
    a = describe_level(df, level, 102.0, ATR, MED_VOL, [level])
    part = score_level(a, len(idxs))["parts"]["rr"]
    near, far = _expected_rr_part(a["rr"]), _expected_rr_part(a["rr_far"])
    check("the score uses rr_near, not rr_far",
          abs(part - near) < 0.02 and (abs(far - near) < 0.02
                                       or abs(part - far) >= 0.02),
          "rr_near %s -> %.2f, rr_far %s -> %.2f, scored %.2f"
          % (a["rr"], near, a["rr_far"], far, part))


# ------------------------------------------------------------------- runner

def main() -> int:
    tests = [
        test_plateau_ties_are_one_touch,
        test_adjacent_pivots_are_one_touch,
        test_proximity_discriminates_inside_admission_range,
        test_cleanliness_distinguishes_three_from_many_traversals,
        test_traversals_measured_since_last_touch,
        test_imminence_is_graded_not_binary,
        test_steady_approach_outranks_sideways_chop,
        test_chop_is_measured_at_all,
        test_room_does_not_reward_air_under_support,
        test_reward_leg_affects_the_score,
        test_resistance_does_not_get_a_free_pass_on_rr,
        test_risk_reward_is_reported,
        test_structural_low_is_reported,
        test_reaction_size_is_reported,
        test_reaction_size_separates_paying_from_dead_levels,
        test_hairline_risk_leg_is_not_a_great_trade,
        test_risk_leg_uses_the_most_recent_structure,
        test_reaction_needs_enough_touches_to_median,
        test_risk_leg_survives_a_shallow_recent_touch,
        test_wick_rejection_depth_is_reported,
        test_band_width_affects_the_score,
        test_freshness_counts_repeat_recent_touches,
        test_freshness_decay_is_convex,
        test_failed_upper_wick_is_a_target,
        test_unfilled_gap_is_a_target,
        test_filled_gap_is_not_a_target,
        test_consolidation_zone_is_a_target,
        test_sr_levels_remain_in_the_target_pool,
        test_near_target_skips_a_trivial_one,
        test_far_target_is_the_strongest_not_the_nearest,
        test_score_uses_the_conservative_rr,
    ]
    for t in tests:
        try:
            t()
        except Exception as exc:                     # noqa: BLE001
            check(t.__name__, False,
                  "raised %s: %s" % (type(exc).__name__, exc))

    width = max(len(n) for n, _, _ in _results)
    print("=" * 78)
    print("LEVELS SCORING DIAGNOSTICS")
    print("=" * 78)
    failed = 0
    for name, ok, detail in _results:
        print("  %-5s %-*s" % ("PASS" if ok else "FAIL", width, name))
        print("        %s" % detail)
        failed += 0 if ok else 1
    print()
    print("%d/%d passing, %d failing"
          % (len(_results) - failed, len(_results), failed))
    print()
    if failed:
        print("Each failure names a part of the scoring redesign that is not")
        print("in place. This file was written red against the pre-redesign")
        print("code on purpose, and every assertion was proven satisfiable")
        print("before the fix was written -- so a failure here is a real gap,")
        print("not an unreachable threshold.")
    else:
        print("Green. Judgement calls baked into these thresholds, all open to")
        print("argument: 5 bars as the touch de-clustering gap, 1.2 ATR as the")
        print("band-width ceiling, 2:1 as where R:R starts to count, and a")
        print("2 ATR median bounce as a full reaction score.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
