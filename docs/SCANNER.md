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

## Detection is untouched

`find_pivots` and `cluster_levels` in `src-python/engine/levels.py` are the
original `sr_scanner.py` maths, byte-identical apart from `cluster_levels`
also returning the pivot indices (`idxs`) so touches can be measured. This
is the part that was already trusted. Do not "improve" it without a reason
and a before/after on real tickers.

- pivot span 3 — a bar that is the extreme within +/- 3 bars
- cluster tolerance 1.0% — greedy price clustering
- the last 3 bars cannot confirm a pivot, so they form no level

## What each level is measured on

`describe_level()` returns plain numbers; the UI sorts on them directly.

| field | meaning | gotcha it was written to avoid |
|---|---|---|
| `dist_atr` | distance to the level in ATR | a fixed % means different things in a calm and a fast market |
| `bars_since_last` | sessions since last touch | — |
| `touch_vol_rel` | mean volume on touch bars / median volume | — |
| `traversals` | full closes through the **band**, side to side | counting centre crossings scored every live level zero, because oscillating inside the band is what a working level looks like |
| `moving_toward` / `eta_bars` | sessions to reach it at the last fortnight's pace | measured by **direction**, not shrinking distance: price falling straight through a level ends up nearer it while actually leaving it behind (NVDA 225.73 -> 212.17 through two levels was being called "approaching") |
| `room_atr` | gap to the next level beyond | `None` means nothing beyond = **clear air**, the most room there is. An early version scored that as zero, the worst |
| `behind_atr` | gap back to the level behind price | — |

ATR is Wilder, 14-period, via `atr_series()`.

## The score

`SCORE_WEIGHTS` in `levels.py`. Current values:

```
proximity     0.20   near enough to matter at all
strength      0.20   more touches
freshness     0.15   touched recently
imminence     0.15   heading there, and soon at this pace
cleanliness   0.12   has not closed clean through it
participation 0.10   touches happened on real volume
room          0.08   clear air beyond it
```

**These weights are guesses.** Nothing proves touches matter more than fresh
volume. They were chosen to be defensible, not because they were measured.
`score_level()` returns the components alongside the number so the ranking
can be argued with rather than believed. Every column in the table is
sortable for the same reason — if you disagree with the blend on a given
morning, sort by the thing you actually care about.

Earning the weights needs outcome data, which is the open work below.

## Known weak spots

- **FLIP badge** is near-constant once minimum touches is 3+, so it carries
  almost no information. Drop it or redefine it (a level that has genuinely
  acted as both support and resistance, with the transition dated).
- **`LevelLadder`** (the per-ticker detail view you get by clicking a row)
  still shows the old columns and surfaces none of the new per-level
  measurements. It is the obvious next UI job.
- **No outcome tracking.** Scans are not saved and trades are not linked to
  the candidate that produced them, so hit rate by attribute is unknowable.

## Open ideas, roughly in order of value

1. **Save each scan** (ticker, level, every component, timestamp) and link a
   Ledger trade back to the scan row that produced it. This is the
   prerequisite for everything else — without it the weights stay guesses.
2. **Hit rate by attribute** once (1) has a few months of data: does
   `touches >= 4` actually beat `touches == 2`? Re-weight on the answer.
3. **Backtest the scanner** over history. Needs care with lookahead: a
   pivot is only confirmed 3 bars later, so a level did not exist on the day
   its middle bar printed.
4. **R-multiples** — needs a stop field on trades, which the Ledger lacks.
5. **MAE / MFE** per trade: how far it went against you before it worked.
6. **Regime tag** on each scan (SPY trend, breadth from the rotation tool)
   so results can be split by market condition.
7. **No-entry log**: candidates looked at and skipped, and why. The most
   under-recorded data in discretionary trading.

## Where the code lives

- `src-python/engine/levels.py` — detection, measurement, scoring
- `src-python/server.py` — `/levels/*` routes, scan settings cached in the
  synced DB under `levels:` keys (which are machine-local by policy, see
  `SYNC-POLICY.md`)
- `src/tools/LevelsView.tsx` — the scan table, filters, sorting
- `src/tools/LevelLadder.tsx` — per-ticker detail (stale, see above)
- `src/lib/api.ts` — `runProximityScan`, `ScanRow`, `LevelMetrics`
