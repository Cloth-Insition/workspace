# Levels scanner

How the morning scan decides what to show you first, why it is built that
way, and what is still unproven. Read this before changing the ranking.

## The design constraint

**Rank, never hard-filter.** The measurements below combine into one score
that sorts the table. They do not eliminate rows. Stacking attributes as
filters — "4+ touches AND fresh AND clear room" — collapses the candidate
list to nothing on most days, which is worse than a noisy list you can skim.

Two things genuinely filter, both single-purpose and both under your control
in the UI: distance in ATR, and minimum touches. Everything else ranks.

## Whose scanner this is

The ranking is built for one seat, deliberately:

- **long only** — a level above price is not an entry
- **enters at the level**, not on the reaction, so there is no confirmation
  to wait for and the historical reaction at that level is the only evidence
- **stop just below the structure that formed the level** — a sharp 2-candle
  move, a cluster of wicks, tight consolidation
- **2:1 minimum R:R**

This is why `room` is measured downward as risk rather than upward as
reward, why R:R carries the largest single weight, and why a resistance
level scores nothing on R:R instead of scoring neutral. None of that is
neutral or general; changing the seat means rebalancing the score.

## Detection

`find_pivots` and `cluster_levels` are the original `sr_scanner.py` maths
with **one** change, made for a reason and with the before/after this
document requires: a *touch* is one test of the level, not one pivot bar.

- pivot span 3 — a bar that is the extreme within +/- 3 bars
- cluster tolerance 1.0% — greedy price clustering
- the last 3 bars cannot confirm a pivot, so they form no level

Two things inflated `touches`, the largest single influence on the old
score:

1. **Plateau ties.** `highs[i] >= window.max()` marked every bar of a run of
   equal highs as its own pivot, so a 3-bar plateau reached the cluster as
   three touches. Now strict on the left and inclusive on the right, which
   picks the first bar of the run.
2. **Temporal clustering.** Two pivots four bars apart in the same 1% band
   are one visit to the band. `touch_events()` groups pivots within
   `TOUCH_GAP_BARS` (5), and `touches` counts groups. `pivot_count` keeps
   the raw number.

`min_touches` therefore filters on **tests of the level**, not pivot bars.
Measured over 30 real tickers, 1y daily:

| min_touches | levels before | after | change |
|---|---|---|---|
| 2 | 338 | 328 | -3.0% |
| 3 | 220 | 205 | -6.8% |
| 4 | 143 | 122 | -14.7% |
| 5 | 83 | 63 | -24.1% |

97% of old level *prices* still have a line within 0.5%: the same lines come
out, counted honestly. The 3% that go are single-visit levels the old count
read as two or more touches. **Practical consequence: min_touches 4 or 5 is
now meaningfully stricter than it was.** If you habitually ran 4, 3 is the
nearer equivalent.

Plateau ties alone were small (-0.3% of pivots, 4 of 30 tickers). Nearly all
the change is temporal de-clustering.

## What each level is measured on

`describe_level()` returns plain numbers; the UI sorts on them directly.
Every field the old version returned is still returned, with the same
meaning.

| field | meaning | gotcha it was written to avoid |
|---|---|---|
| `dist_atr` | distance to the level in ATR | a fixed % means different things in a calm and a fast market |
| `bars_since_last` | sessions since last touch | — |
| `recent_touches` | touches inside the last 60 sessions | one recent touch and three recent touches used to tie |
| `touch_vol_rel` | mean volume on touch bars / median volume | — |
| `traversals` | full closes through the **band**, side to side, **since the last touch** | counting centre crossings scored every live level zero; counting from the *first* touch condemned a level for breaks that predate its current behaviour |
| `traversals_ever` | the same, since the level formed | kept, because a level that broke and reclaimed is the real FLIP |
| `moving_toward` / `eta_bars` | direction and sessions-to-arrival from a **least-squares slope** | mean absolute change is random-walk speed: a name oscillating and going nowhere scored *faster* than a steady trender, handing top imminence to sideways chop |
| `efficiency` | net displacement / gross travel over 21 bars | "it has been chopping sideways" as a number |
| `band_atr` | band width in ATR | how cleanly the line is drawn; ranges 0.03–1.14 in practice and used to be scored nowhere |
| `structural_low` | lowest low of the **most recent touch event** | the stop anchor. `min()` across every touch bar picked the year's deepest wick, reading nine points under a level on RTX and scoring a 6-touch level with a 3.17 ATR bounce at 0.05 on R:R. "A previous significant move" means a recent one |
| `structural_low_ever` | the same, across all touch bars | kept |
| `risk_anchor` | `min(structural_low, band lo)` | a touch can dip into the band without closing below its mean price, leaving a low *above* `center`. Measured from the centre that gives a negative risk leg, which read as unmeasurable on 49% of long rows — all of them then collecting the neutral free pass. The stop sits below the band, not below the mean of the clustered pivots |
| `risk_atr` | level to risk anchor, in ATR | the risk leg |
| `risk_unmeasurable` | no structure to stop under | a hairline under `MIN_RISK_ATR` is not a 300:1 trade, it is an unmeasurable one. NFLX reached second in the universe on a 0.036 ATR risk leg before this |
| `reward_near_atr` | level to the nearest overhead target worth trading to | the reward leg. It used to be "the next detected S/R cluster above price", which only accidentally catches congestion and is blind to a rejected high or an unfilled gap — two of the three things actually traded to |
| `reward_far_atr` | level to the **strongest** structure at or beyond the near one | the optimistic case, reported beside the conservative one. Never nearer than `reward_near_atr` |
| `target_near` / `target_near_kind` | the price and which of `sr` / `wick` / `gap` / `consol` | so a target can be argued with instead of trusted |
| `target_far` / `target_far_kind` | the same for the optimistic target | — |
| `target_near_trivial` | every overhead structure is nearer than `MIN_REWARD_ATR` | a trivially close target is a poor reward, not an unmeasurable one, so it is reported rather than dropped to neutral |
| `rr` | `reward_near_atr` / `risk_atr` | the conservative ratio, and the one the score uses |
| `rr_far` | `reward_far_atr` / `risk_atr` | reported only |
| `floor_gap_atr` | gap down to the level beneath | what catches a failed hold |
| `reaction_atr` | median favourable excursion over the 10 bars after prior touches | whether this level has ever actually paid |
| `wick_atr` | band top to structural low | "a cluster of wicks", measured |
| `room_atr` / `behind_atr` | unchanged, for the existing table | `room_atr` None still means nothing beyond |

ATR is Wilder, 14-period, via `atr_series()`.

**Lookahead discipline** on `reaction_atr`: a touch needs 10 forward bars to
have an outcome, and a pivot is not confirmed until 3 bars later, so only
touches at least 13 bars old contribute. A touch bar also has to have
actually overlapped the band — a forward *maximum* is not robust to a stray
index the way the structural low's `min()` is, and without that guard a name
oscillating well above a level read as a large bounce off a level it never
reached.

## Overhead targets

`overhead_targets()` pools four kinds of structure above price and they
compete on distance:

| kind | detection | strength |
|---|---|---|
| `sr` | a detected S/R cluster above price | touches / 2 |
| `wick` | upper wick >= `WICK_FRAC` of the bar's range and >= `WICK_MIN_ATR` deep, whose high was **never exceeded afterward** | wick depth in ATR |
| `gap` | a gap down (`high[i] < low[i-1]`) of at least `GAP_MIN_ATR`, whose pre-gap low price has not traded back through | gap size in ATR |
| `consol` | contiguous windows of `CONSOL_BARS` staying inside `CONSOL_MAX_ATR`, targeted at the base of the zone | duration / `CONSOL_BARS` |

`rr` takes the nearest target leaving at least `MIN_REWARD_ATR` of reward;
`rr_far` takes the strongest structure at or beyond that one, so the
optimistic figure is never nearer than the conservative one. Only `rr` is
scored.

`strength` is deliberately crude and only orders the optimistic target. It
is a calibration knob, not a finding.

Measured over the full universe (2% threshold, min_touches 3, 63 long rows),
the near target is a `wick` 42 times, `sr` 20 times and `consol` once, and a
`gap` never — gaps do win as the *far* target. Unbroken rejection highs are
simply the most numerous overhead structure, so one is usually nearest. If
that proves wrong in practice, `WICK_FRAC` and `WICK_MIN_ATR` are the levers.

## The score

`SCORE_WEIGHTS` in `levels.py`. Current values:

```
rr            0.18   reward against the structural stop, 2:1 minimum
reaction      0.14   prior touches actually paid
efficiency    0.12   arriving on a trend, not chopping sideways
strength      0.10   more distinct tests of the level
imminence     0.09   heading there, and soon at this drift
freshness     0.08   touched recently, and more than once
cleanliness   0.08   has not closed clean through it since the last touch
band          0.07   a tight line you can define risk against
proximity     0.06   near enough to matter at all
room          0.04   something catches it if the hold fails
participation 0.04   touches happened on real volume
```

**These weights are still guesses.** What changed is that they are no longer
guesses about components that could not discriminate. The previous set
declared 0.20 for `proximity` and 0.12 for `cleanliness`; measured across a
real scan, proximity varied by 0.07 (sd) because `NEAR_ATR` was 6.0 while the
distance filter admits nothing beyond ~1.5 ATR, and 89% of rows scored
`cleanliness` exactly 0 because `1 - traversals/3` floors at three when real
traversal counts reach 28. The old score was 0.93 rank-correlated with
`strength + imminence + freshness` alone, and 0.89 with `imminence` by
itself.

Declared weight versus **effective influence** (weight × spread across a real
scan) is now close, where before it was not:

| component | declared | effective |
|---|---|---|
| rr | 0.18 | 18.2% |
| reaction | 0.14 | 15.9% |
| strength | 0.10 | 13.3% |
| efficiency | 0.12 | 11.6% |
| imminence | 0.09 | 9.9% |
| freshness | 0.08 | 7.7% |
| cleanliness | 0.08 | 6.3% |
| proximity | 0.06 | 5.4% |
| band | 0.07 | 5.2% |
| participation | 0.04 | 3.4% |
| room | 0.04 | 3.2% |

Before re-weighting anything, re-run that measurement. A component with no
spread is a constant offset and its declared weight is a fiction.

`score_level()` returns the components alongside the number so the ranking
can be argued with rather than believed. Every column in the table is
sortable for the same reason.

### Missing data

A measurement that could not be computed scores `NEUTRAL` (0.5), never 0.
Punishing a level for absent data is how the first version of `room` ranked
clear air as the worst case instead of the best.

**But unmeasurable and not-applicable are different.** A level above price
has no long entry, so it scores 0 on `rr` rather than neutral. Scoring it
neutral handed every resistance row half marks on the heaviest component and
floated rows you cannot take above real support setups at 1.4:1 and 0.7:1 —
a regression caught only by running a live scan after the suite was green.

## Calibration still open to argument

These are judgement calls, not findings:

- `TOUCH_GAP_BARS` 5 — the gap that makes two pivots one touch
- `BAND_MAX_ATR` 1.2 — above this a band is a zone, not a line
- `RR_FLOOR` 1.0 / `RR_SPAN` 5.0 — a 2:1 setup scores 0.20 on the heaviest
  component, near the bottom. Defensible (2:1 is the *minimum*, not good) but
  it means only 6:1+ scores well
- `MIN_RISK_ATR` 0.10 — now routes to NEUTRAL rather than being floored and
  divided. 8% of long rows land there (was 49% before the band-low anchor)
- **Risk legs are tight**: median 0.31 ATR, p25 0.21. On RTX that is a ~$0.78
  stop on a $193 stock. If real stops are nearer 0.5-1.0 ATR then every `rr`
  here is roughly double what it should be, and the component's saturation
  goes away on its own. This needs a human answer, not a constant
- `rr_part` still pins at 1.00 on 33% of rows (median rr 3.7 against an
  `RR_SPAN` that saturates at 6:1). Widen the span, or narrow the risk leg
- NEUTRAL 0.5 for an unmeasurable leg still beats any *measured* R:R below
  3.5:1. Three separate bugs have now had this shape
- `rr_far` saturates: p75 is 19.7 against a `MAX_RR` of 20. It is reported
  rather than scored so this is cosmetic, but the cap is doing most of the
  work at the top of the range
- `CLEAR_ABOVE_RR` is now effectively dead code: with wicks in the pool, no
  row in a full-universe scan has nothing overhead
- `CONSOL_MAX_ATR` 0.8 over 5 bars means any quiet week counts as
  congestion, including a smooth drift. A zone that is monotonically
  trending is arguably not consolidation
- `REACTION_FULL_ATR` 2.0 — a 2 ATR median bounce as a full score
- `CLEAR_ABOVE_RR` 1.0 — clear air overhead scores top marks by the same
  logic as `room_atr` None. It may also just mean short history

## Known weak spots

- **Resistance rows are still rows.** They rank down rather than being
  converted into target data for the support rows beneath them. That
  restructure is agreed but not built, and is not covered by a test.
- **FLIP badge** is near-constant (78% of rows at min_touches 2), so it
  carries almost no information. `traversals_ever` versus `traversals` now
  contains what a real flip is — a level that broke and was reclaimed, with
  the transition dateable — but nothing uses it yet.
- **`LevelLadder`** still shows the old columns.
- **The new fields are invisible.** `rr`, `reaction_atr`, `efficiency`,
  `band_atr`, `risk_atr` and `structural_low` are all returned and none are
  rendered or sortable. That undercuts the whole "argue with the blend by
  sorting" principle and is the next job.
- **`CHUNK_PAUSE` is still unused.** `proximity_scan` fetches in a tight
  loop with no inter-request spacing. It gets away with it at 160 tickers
  (0.31s/ticker, ~50s); it will not at 500.
- **No outcome tracking.** Scans are not saved and trades are not linked to
  the candidate that produced them.

## Open ideas, roughly in order of value

1. **Surface the new columns** in `LevelsView` and `LevelLadder`, sortable.
2. **Resistance as target data** rather than candidate rows — with tests
   first, since it changes what appears in the table.
3. **Retrospective touch-outcome study.** Every level carries 2–11 historical
   touches and `reaction_atr` now measures what followed each one. Across the
   universe that is hundreds of natural experiments available immediately,
   and it is the route to earning the weights that does **not** depend on the
   Ledger's size. Same lookahead care as a backtest, much less machinery.
3. **Retro-score the logged trades.** Reconstruct the scan as of each entry
   date, using only bars up to it. ~45 labelled rows today. Mostly a *recall*
   check — only ~15% were scanner-sourced — and if trades that worked would
   not have been flagged at all, that is a detection gap and a reason.
4. **Save each scan** (ticker, level, every component, timestamp) and link a
   Ledger trade back to the row that produced it. Notes: ~150 rows/day is
   megabytes a year; `trades.extra` is already a JSON catch-all so no
   migration is needed; and because `levels:` keys are machine-local by
   policy while trades sync, the snapshot must be **copied onto the trade**,
   not referenced by id, or the link dangles across machines.
5. **No-entry log**: candidates looked at and skipped, and why. With the two
   real skip reasons now measured (`rr`, `efficiency`), this is how you
   confirm the ranking moved the way your eye already does. The most
   under-recorded data in discretionary trading.
6. **Hit rate by attribute**, once there is outcome data. Check each
   component univariately first — a component with no signal alone should not
   be in a fit — and keep weights coarse (0.05) so the ranking does not
   advertise precision it has not got. Note that ~45 trades cannot support
   fitting 11 weights; that is what (2) is for.
7. **Widen the universe** to the full S&P 500, keeping the sector map so the
   filter still works, *after* the ranking is trusted — a longer list under a
   bad ordering is just more skimming. Wire up `CHUNK_PAUSE` first.
8. **Regime tag** on each scan (SPY trend, breadth from the rotation tool)
   so results can be split by market condition. Also: if 20 rows fire because
   SPY is at a level, they are one bet, not 20.
9. **Volume-at-price.** Pivots find price extremes, not where shares changed
   hands. Distributing each bar's volume across its range into price bins is
   cheap and is genuinely new information rather than another slice of the
   same pivots.
10. **Confluence** — a 50/200 SMA inside the band, a round number, the
    52-week extreme, a gap edge. Ranks, never filters.

## Tests

`tests/test_levels_scoring.py` — 32 checks, offline and deterministic, no
yfinance and no credentials. Every one was written asserting the desired
behaviour and **shown failing** against the pre-redesign code first, then
shown satisfiable against a throwaway reference implementation, because a
test that can never pass is worse than no test. Two of the fixtures were
wrong in a way that made their assertions vacuous — touch bars on bars that
never touched the level, a "poor R:R" target that sat below price and so read
as clear air, and a "tight" band of 0.05 ATR that was itself below the
hairline threshold and so tested the unmeasurable path instead of band width.
None were caught by inspection.

Three of them exist because of bugs found by running a **live
scan** after the suite was already green: resistance rows collecting a
neutral R:R, the risk leg taken from the year's deepest wick, and the
hairline 300:1. Source-level tests passing while the real thing is wrong is
this repo's recurring failure mode and it recurred here.

A fourth came from a test that passed on a near-miss: a 0.6-tolerance check
on a consolidation target was satisfied by an unrelated patch 0.53 away,
hiding a merge that joined non-contiguous tight windows and dragged zone
bases toward price. Tolerances wide enough to pass are wide enough to hide.

It is **not** in `tests/run_all.py`: add it to `OFFLINE_TESTS` whenever the
suite is green and expected to stay so.

## Where the code lives

- `src-python/engine/levels.py` — detection, measurement, scoring
- `src-python/server.py` — `/levels/*` routes, scan settings cached in the
  synced DB under `levels:` keys (which are machine-local by policy, see
  `SYNC-POLICY.md`)
- `src/tools/LevelsView.tsx` — the scan table, filters, sorting
- `src/tools/LevelLadder.tsx` — per-ticker detail (stale, see above)
- `src/lib/api.ts` — `runProximityScan`, `ScanRow`, `LevelMetrics`
