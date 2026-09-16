import { useMemo, useState } from "react";
import { type VolumeBlock, type VolumeDay } from "../lib/api";
import "../styles/volume.css";

function fmtDollar(v: number): string {
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toFixed(0)}`;
}

// Roughly how many sessions each range covers (21 trading days a month).
const RANGES = [
  { key: "1M", bars: 21 },
  { key: "3M", bars: 63 },
  { key: "6M", bars: 126 },
  { key: "1Y", bars: 252 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

// Breadth drives both the direction and the depth of a bar's colour. 0.5 is
// an even day; BREADTH_FULL either side of it is as deep as the colour gets.
// Calibrated against a real year of this universe, where breadth runs
// median 52%, 10th percentile 29%, 90th 71%: at 0.30 about a sixth of
// sessions reach near-full colour and a seventh stay near-neutral, so the
// scale is actually used without every other day shouting.
const BREADTH_FULL = 0.30;
const MIN_TINT = 0.22;   // a directional day is never so faint it reads as neutral

function tint(day: VolumeDay): { dir: "up" | "down" | "flat"; strength: number } {
  if (day.up === null || !day.n) return { dir: "flat", strength: 0 };
  const share = day.up / day.n;
  const off = share - 0.5;
  if (Math.abs(off) < 1e-9) return { dir: "flat", strength: 0 };
  const strength = Math.min(1, Math.abs(off) / BREADTH_FULL);
  return { dir: off > 0 ? "up" : "down", strength: MIN_TINT + (1 - MIN_TINT) * strength };
}

function tooltip(day: VolumeDay, isToday: boolean): string {
  const bits = [day.d, fmtDollar(day.v)];
  if (day.up !== null && day.n) {
    const pct = Math.round((day.up / day.n) * 100);
    bits.push(`${day.up}/${day.n} up (${pct}%)`);
  }
  if (day.spy !== null && day.spy !== undefined) {
    bits.push(`SPY ${day.spy >= 0 ? "+" : ""}${day.spy.toFixed(2)}%`);
  }
  return bits.join(" · ") + (isToday ? " · today, may be partial" : "");
}

/**
 * Volume read above the rotation table. Answers: is today heavy or light, and
 * if there's energy, which sector holds it. The universe bar chart gives the
 * day-vs-day comparison (a number like "$847B" is meaningless without the
 * neighbouring days); the per-sector bars show concentration.
 *
 * Bars are coloured by that session's breadth, so heavy days read as buying
 * or selling at a glance rather than just "busy".
 */
export function VolumePanel({ volume }: { volume: VolumeBlock }) {
  const [range, setRange] = useState<RangeKey>("1M");

  // A scan cached by an older build has no `daily`; show what it does have.
  const all: VolumeDay[] = useMemo(
    () =>
      volume.daily ??
      (volume.universe_daily ?? []).map(([d, v]) => ({ d, v, up: null, n: null, spy: null })),
    [volume.daily, volume.universe_daily],
  );

  // Offer a range only when there is more history than the range below it.
  const available = RANGES.filter((_, i) => i === 0 || all.length > RANGES[i - 1].bars);
  const active = available.some((r) => r.key === range) ? range : available[available.length - 1].key;
  const bars = RANGES.find((r) => r.key === active)!.bars;
  const daily = all.slice(-bars);

  if (!daily.length) return null;

  const max = Math.max(...daily.map((d) => d.v));
  const todayDate = volume.today;
  const todayTotal = daily[daily.length - 1]?.v ?? 0;

  // Average of the prior days (excluding today) for the headline comparison.
  const prior = daily.slice(0, -1).map((d) => d.v);
  const avgPrior = prior.length ? prior.reduce((a, b) => a + b, 0) / prior.length : 0;
  const relToday = avgPrior ? todayTotal / avgPrior : 0;

  return (
    <div className="vol">
      <div className="vol-head">
        <span className="vol-title">Universe dollar volume</span>
        <span className="vol-today mono">
          {fmtDollar(todayTotal)}
          {avgPrior > 0 && (
            <span
              className={`vol-rel ${relToday >= 1 ? "hot" : "cool"}`}
              title={`today vs the average of the ${daily.length} sessions shown`}
            >
              {relToday.toFixed(2)}× {active} avg
            </span>
          )}
        </span>
      </div>

      {available.length > 1 && (
        <div className="vol-ranges">
          {available.map((r) => (
            <button
              key={r.key}
              className={`vol-range ${r.key === active ? "active" : ""}`}
              onClick={() => setRange(r.key)}
            >
              {r.key}
            </button>
          ))}
        </div>
      )}

      <div className={`vol-chart ${daily.length > 80 ? "dense" : ""}`}>
        {daily.map((day) => {
          const isToday = day.d === todayDate;
          const h = max > 0 ? Math.max(2, (day.v / max) * 100) : 2;
          const { dir, strength } = tint(day);
          return (
            <div
              key={day.d}
              className={`vol-bar-wrap ${isToday ? "today" : ""}`}
              title={tooltip(day, isToday)}
            >
              <div
                className={`vol-bar ${dir}`}
                style={{ height: `${h}%`, ["--i" as string]: strength.toFixed(3) }}
              />
            </div>
          );
        })}
      </div>
      <div className="vol-axis">
        <span>{daily[0].d.slice(5)}</span>
        <span className="vol-axis-note">
          {daily.length} sessions · colour is that day’s breadth · today’s bar may be partial
        </span>
        <span>{daily[daily.length - 1].d.slice(5)}</span>
      </div>

      {/* Per-sector: today vs each sector's own 20-day average */}
      <div className="vol-sectors">
        <span className="vol-sectors-label">today by sector · vs own 20-day avg</span>
        <div className="vol-sector-grid">
          {volume.sectors.map((s) => {
            // Bar width scaled so 1.0× sits at the midpoint; >1 leans hot.
            const pct = Math.min(100, (s.rel / 2) * 100);
            return (
              <div key={s.etf} className="vol-sector-row" title={`${s.name} · ${fmtDollar(s.today)} today`}>
                <span className="vol-sector-etf mono">{s.etf}</span>
                <div className="vol-sector-track">
                  <div
                    className={`vol-sector-fill ${s.rel >= 1.2 ? "hot" : s.rel < 0.8 ? "cool" : ""}`}
                    style={{ width: `${pct}%` }}
                  />
                  <span className="vol-sector-mid" />
                </div>
                <span className={`vol-sector-rel mono ${s.rel >= 1.2 ? "hot" : s.rel < 0.8 ? "cool" : ""}`}>
                  {s.rel.toFixed(2)}×
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
