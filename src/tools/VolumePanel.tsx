import { type VolumeBlock } from "../lib/api";
import "../styles/volume.css";

function fmtDollar(v: number): string {
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toFixed(0)}`;
}

/**
 * Volume read above the rotation table. Answers: is today heavy or light, and
 * if there's energy, which sector holds it. The universe bar chart gives the
 * day-vs-day comparison (a number like "$847B" is meaningless without the
 * neighbouring days); the per-sector bars show concentration.
 */
export function VolumePanel({ volume }: { volume: VolumeBlock }) {
  const daily = volume.universe_daily;
  if (!daily.length) return null;

  const max = Math.max(...daily.map(([, v]) => v));
  const todayDate = volume.today;
  const todayTotal = daily[daily.length - 1]?.[1] ?? 0;

  // Average of the prior days (excluding today) for the headline comparison.
  const prior = daily.slice(0, -1).map(([, v]) => v);
  const avgPrior = prior.length ? prior.reduce((a, b) => a + b, 0) / prior.length : 0;
  const relToday = avgPrior ? todayTotal / avgPrior : 0;

  return (
    <div className="vol">
      <div className="vol-head">
        <span className="vol-title">Universe dollar volume</span>
        <span className="vol-today mono">
          {fmtDollar(todayTotal)}
          {avgPrior > 0 && (
            <span className={`vol-rel ${relToday >= 1 ? "hot" : "cool"}`}>
              {relToday.toFixed(2)}× avg
            </span>
          )}
        </span>
      </div>

      <div className="vol-chart">
        {daily.map(([date, v], i) => {
          const isToday = date === todayDate;
          const h = max > 0 ? Math.max(2, (v / max) * 100) : 2;
          return (
            <div
              key={date}
              className={`vol-bar-wrap ${isToday ? "today" : ""}`}
              title={`${date} · ${fmtDollar(v)}${
                i === daily.length - 1 ? " (today, may be partial)" : ""
              }`}
            >
              <div className="vol-bar" style={{ height: `${h}%` }} />
            </div>
          );
        })}
      </div>
      <div className="vol-axis">
        <span>{daily[0][0].slice(5)}</span>
        <span className="vol-axis-note">
          last {daily.length} sessions · today’s bar may be partial in pre-market
        </span>
        <span>{daily[daily.length - 1][0].slice(5)}</span>
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
