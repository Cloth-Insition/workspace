import { useEffect, useMemo, useRef, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import {
  type RotationPayload,
  type VolumeBlock,
} from "../lib/api";
import { useRotation } from "../lib/rotationStore";
import { Calendar } from "./Calendar";
import { LevelLadder } from "./LevelLadder";
import { VolumePanel } from "./VolumePanel";
import "../styles/rotation.css";

// ---- Return / breadth maths, ported from the original dashboard's in-browser JS ----

function priceMap(p: RotationPayload, t: string): Record<string, number> {
  const m: Record<string, number> = {};
  (p.series[t] || []).forEach(([d, c]) => (m[d] = c));
  return m;
}
function datesOf(p: RotationPayload, t: string): string[] {
  return (p.series[t] || []).map(([d]) => d);
}
function priceOn(map: Record<string, number>, dates: string[], target: string) {
  if (map[target] !== undefined) return map[target];
  let best: string | null = null;
  for (const d of dates) {
    if (d <= target) best = d;
    else break;
  }
  return best !== null ? map[best] : null;
}
function spanReturn(p: RotationPayload, t: string, start: string, end: string) {
  const map = priceMap(p, t);
  const dates = datesOf(p, t);
  if (!dates.length) return null;
  const a = priceOn(map, dates, start);
  const b = priceOn(map, dates, end);
  if (a === null || b === null || a === 0) return null;
  return (b / a - 1) * 100;
}
function breadthFor(p: RotationPayload, etf: string, start: string, end: string) {
  const holds = p.sectors[etf]?.holdings || [];
  let up = 0,
    total = 0;
  for (const h of holds) {
    const r = spanReturn(p, h, start, end);
    if (r !== null) {
      total++;
      if (r > 0) up++;
    }
  }
  return total ? { up, total } : null;
}

interface Row {
  etf: string;
  name: string;
  span: number;
  breadth: { up: number; total: number } | null;
}

type Drill =
  | { level: "sectors" }
  | { level: "holdings"; etf: string }
  | { level: "levels"; etf: string; ticker: string };

// (Drill state itself now lives in rotationStore so it survives tab switches;
// this local type alias is kept for the Breadcrumb/SectorTable prop signatures.)

export function RotationView() {
  const {
    data,
    loading,
    error: err,
    cachedAt,
    drill,
    range,
    setDrill,
    setRange,
    refresh,
  } = useRotation();

  if (loading && !data)
    return <div className="rot-msg">Fetching sector data…</div>;
  if (err && !data) return <div className="rot-msg rot-err">{err}</div>;
  if (!data || !range) return null;

  // All trading dates that actually have price data — feeds the calendar.
  const allDates = Array.from(
    new Set(
      Object.keys(data.sectors).flatMap((etf) => datesOf(data, etf))
    )
  ).sort();

  // The active span comes from the calendar selection, ordered defensively.
  const start = range.start <= range.end ? range.start : range.end;
  const end = range.start <= range.end ? range.end : range.start;
  const sessions = allDates.filter((d) => d >= start && d <= end).length - 1;

  const rows: Row[] = Object.keys(data.sectors)
    .filter((t) => t !== "SPY")
    .map((etf) => ({
      etf,
      name: data.sectors[etf].name,
      span: spanReturn(data, etf, start, end) ?? NaN,
      breadth: breadthFor(data, etf, start, end),
    }))
    .filter((r) => !isNaN(r.span))
    .sort((a, b) => b.span - a.span);

  const spySpan = spanReturn(data, "SPY", start, end);

  return (
    <div className="rot">
      <Breadcrumb drill={drill} setDrill={setDrill} />

      {drill.level === "sectors" && (
        <SectorTable
          data={data}
          rows={rows}
          allDates={allDates}
          start={start}
          end={end}
          sessions={sessions}
          spySpan={spySpan}
          stamp={data.generated_human}
          cachedAt={cachedAt}
          loading={loading}
          volume={data.volume}
          onRefresh={refresh}
          onRange={(s, e) => setRange({ start: s, end: e })}
          onOpen={(etf) => setDrill({ level: "holdings", etf })}
        />
      )}

      {drill.level === "holdings" && (
        <HoldingsTable
          data={data}
          etf={drill.etf}
          start={start}
          end={end}
          onOpen={(ticker) =>
            setDrill({ level: "levels", etf: drill.etf, ticker })
          }
        />
      )}

      {drill.level === "levels" && <LevelLadder ticker={drill.ticker} />}
    </div>
  );
}

function Breadcrumb({
  drill,
  setDrill,
}: {
  drill: Drill;
  setDrill: (d: Drill) => void;
}) {
  if (drill.level === "sectors") return null;
  return (
    <div className="crumb">
      <span className="crumb-link" onClick={() => setDrill({ level: "sectors" })}>
        Rotation
      </span>
      <i className="ti ti-chevron-right" aria-hidden="true" />
      {drill.level === "holdings" ? (
        <span className="crumb-here">{drill.etf}</span>
      ) : (
        <>
          <span
            className="crumb-link"
            onClick={() => setDrill({ level: "holdings", etf: drill.etf })}
          >
            {drill.etf}
          </span>
          <i className="ti ti-chevron-right" aria-hidden="true" />
          <span className="crumb-here">{drill.ticker}</span>
        </>
      )}
    </div>
  );
}

function pct(n: number) {
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}
function dirClass(n: number) {
  return n >= 0 ? "up" : "down";
}

function relativeAge(cachedAt: number | null, fallback: string): string {
  if (!cachedAt) return fallback;
  const secs = Math.floor(Date.now() / 1000) - cachedAt;
  if (secs < 90) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

// ─────────────────────── Sector paths ───────────────────────
//
// The table shows where each sector ENDED. This shows how it got there —
// every sector ETF rebased to 0% at the calendar's start date, so a sector
// that round-tripped down 4% before closing +2% reads completely differently
// from one that ground up in a straight line.
//
// Colour: at rest each line carries the same muted up/down tint as its row in
// the table directly above, so the two read as one object. Eleven separately
// hued lines would be a rainbow and would break the one-accent rule, so
// identification is done by emphasis instead — hovering a table row or a
// legend chip lifts that one line to the accent and drops the rest back.
// SPY keeps the gold benchmark thread it has in the table.

interface PathPoint {
  d: string;
  [etf: string]: string | number;
}

/**
 * Width of an element, tracked live.
 *
 * Deliberately NOT recharts' ResponsiveContainer here. App.tsx keeps the
 * Rotation view mounted behind `display: none` so its state survives a tab
 * switch, which means this chart can mount at zero width — if the rotation
 * data lands while you're on another tab. ResponsiveContainer latches at that
 * zero and never draws, leaving a permanently blank panel. Measuring the
 * container ourselves and re-measuring on every observer callback survives
 * being mounted hidden and then revealed.
 *
 * FxView can keep using ResponsiveContainer: it only ever mounts while its
 * own tab is active, so it never starts life at zero width.
 */
function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWidth(el.getBoundingClientRect().width);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return [ref, width] as const;
}

function buildPaths(
  p: RotationPayload,
  etfs: string[],
  allDates: string[],
  start: string,
  end: string
): { points: PathPoint[]; drawn: string[] } {
  const windowDates = allDates.filter((d) => d >= start && d <= end);
  const bases: Record<string, number> = {};
  const lookups: Record<string, { map: Record<string, number>; dates: string[] }> = {};

  for (const t of etfs) {
    const map = priceMap(p, t);
    const dates = datesOf(p, t);
    if (!dates.length) continue;
    const base = priceOn(map, dates, start);
    // A missing or zero base can't be indexed against — drop the line rather
    // than drawing a divide-by-zero spike.
    if (base === null || base === 0) continue;
    bases[t] = base;
    lookups[t] = { map, dates };
  }

  const drawn = Object.keys(bases);
  const points: PathPoint[] = windowDates.map((d) => {
    const row: PathPoint = { d };
    for (const t of drawn) {
      const v = priceOn(lookups[t].map, lookups[t].dates, d);
      if (v !== null) row[t] = (v / bases[t] - 1) * 100;
    }
    return row;
  });

  return { points, drawn };
}

function PathTooltip({
  active,
  payload,
  label,
  names,
  emphasis,
}: {
  active?: boolean;
  payload?: { dataKey: string; value: number }[];
  label?: string;
  names: Record<string, string>;
  emphasis: string | null;
}) {
  if (!active || !payload || !payload.length) return null;
  const ranked = [...payload]
    .filter((e) => typeof e.value === "number")
    .sort((a, b) => b.value - a.value);
  return (
    <div className="path-tip">
      <div className="path-tip-date mono">{label}</div>
      {ranked.map((e) => (
        <div
          key={e.dataKey}
          className={`path-tip-row ${e.dataKey === emphasis ? "lead" : ""} ${
            e.dataKey === "SPY" ? "bench" : ""
          }`}
        >
          <span className="path-tip-etf mono">{e.dataKey}</span>
          <span className="path-tip-name">{names[e.dataKey] ?? ""}</span>
          <span className={`path-tip-val mono ${dirClass(e.value)}`}>
            {pct(e.value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function SectorPaths({
  data,
  rows,
  allDates,
  start,
  end,
  sessions,
  emphasis,
  onEmphasis,
}: {
  data: RotationPayload;
  rows: Row[];
  allDates: string[];
  start: string;
  end: string;
  sessions: number;
  emphasis: string | null;
  onEmphasis: (etf: string | null) => void;
}) {
  const [wrapRef, width] = useElementWidth<HTMLDivElement>();
  const etfs = useMemo(() => rows.map((r) => r.etf), [rows]);

  // Rebased purely from the payload's daily series — same data Calendar uses
  // to recompute the table, so no refetch and no backend involvement.
  const { points, drawn } = useMemo(
    () => buildPaths(data, [...etfs, "SPY"], allDates, start, end),
    [data, etfs, allDates, start, end]
  );

  const names = useMemo(() => {
    const m: Record<string, string> = {};
    for (const etf of Object.keys(data.sectors)) m[etf] = data.sectors[etf].name;
    return m;
  }, [data]);

  // End-of-span direction per sector, for the resting tint.
  const endReturn = useMemo(() => {
    const m: Record<string, number> = {};
    for (const r of rows) m[r.etf] = r.span;
    const spy = spanReturn(data, "SPY", start, end);
    if (spy !== null) m["SPY"] = spy;
    return m;
  }, [rows, data, start, end]);

  if (sessions < 1) {
    return (
      <div className="paths">
        <div className="paths-head">
          <span className="paths-title">Sector paths</span>
        </div>
        <div className="paths-empty">
          Pick a span of at least two sessions to draw the paths.
        </div>
      </div>
    );
  }

  // Draw the emphasized line last so it sits on top of the tangle.
  const order = drawn
    .slice()
    .sort((a, b) =>
      a === emphasis ? 1 : b === emphasis ? -1 : 0
    );

  function strokeFor(etf: string): string {
    if (etf === emphasis) return "var(--accent)";
    if (etf === "SPY") return "var(--benchmark)";
    return (endReturn[etf] ?? 0) >= 0 ? "var(--up)" : "var(--down)";
  }
  function opacityFor(etf: string): number {
    if (emphasis === null) return etf === "SPY" ? 0.6 : 0.5;
    return etf === emphasis ? 1 : 0.1;
  }

  return (
    <div className="paths">
      <div className="paths-head">
        <span className="paths-title">Sector paths</span>
        <span className="paths-sub mono">
          indexed to 0% at {start}
        </span>
      </div>

      <div
        className="paths-chart"
        ref={wrapRef}
        onMouseLeave={() => onEmphasis(null)}
      >
        {width > 0 && (
          <LineChart
            width={width}
            height={280}
            data={points}
            margin={{ top: 8, right: 10, bottom: 4, left: 0 }}
          >
            <CartesianGrid stroke="var(--line-faint)" vertical={false} />
            <XAxis
              dataKey="d"
              tickFormatter={(d: string) => d.slice(5)}
              stroke="var(--line)"
              tick={{ fill: "var(--text-2)", fontSize: 10 }}
              tickLine={false}
              minTickGap={38}
            />
            <YAxis
              domain={["auto", "auto"]}
              tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`}
              stroke="var(--line)"
              tick={{ fill: "var(--text-2)", fontSize: 10 }}
              tickLine={false}
              width={54}
            />
            {/* The 0% line is the whole reference — every path starts here. */}
            <ReferenceLine y={0} stroke="var(--line)" strokeWidth={1} />
            <Tooltip
              content={<PathTooltip names={names} emphasis={emphasis} />}
              cursor={{ stroke: "var(--line)", strokeWidth: 1 }}
            />
            {order.map((etf) => (
              <Line
                key={etf}
                type="monotone"
                dataKey={etf}
                stroke={strokeFor(etf)}
                strokeOpacity={opacityFor(etf)}
                strokeWidth={etf === emphasis ? 2 : 1.2}
                strokeDasharray={etf === "SPY" ? "4 3" : undefined}
                dot={false}
                activeDot={false}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </LineChart>
        )}
      </div>

      <div className="paths-legend">
        {rows.map((r) => (
          <span
            key={r.etf}
            className={`paths-chip ${dirClass(r.span)} ${
              r.etf === emphasis ? "on" : ""
            } ${emphasis && r.etf !== emphasis ? "off" : ""}`}
            onMouseEnter={() => onEmphasis(r.etf)}
            onMouseLeave={() => onEmphasis(null)}
            title={`${r.name} · ${pct(r.span)}`}
          >
            {r.etf}
          </span>
        ))}
        <span
          className={`paths-chip bench ${emphasis === "SPY" ? "on" : ""} ${
            emphasis && emphasis !== "SPY" ? "off" : ""
          }`}
          onMouseEnter={() => onEmphasis("SPY")}
          onMouseLeave={() => onEmphasis(null)}
          title="S&P 500 benchmark"
        >
          SPY
        </span>
      </div>
    </div>
  );
}

function SectorTable({
  data,
  rows,
  allDates,
  start,
  end,
  sessions,
  spySpan,
  stamp,
  cachedAt,
  loading,
  volume,
  onRefresh,
  onRange,
  onOpen,
}: {
  data: RotationPayload;
  rows: Row[];
  allDates: string[];
  start: string;
  end: string;
  sessions: number;
  spySpan: number | null;
  stamp: string;
  cachedAt: number | null;
  loading: boolean;
  volume?: VolumeBlock;
  onRefresh: () => void;
  onRange: (start: string, end: string) => void;
  onOpen: (etf: string) => void;
}) {
  // Which line the chart lifts to the accent. Driven by hovering either a
  // table row or a legend chip, so the table and the chart stay one object.
  const [emphasis, setEmphasis] = useState<string | null>(null);

  return (
    <>
      <div className="rot-head">
        <h1>Sector rotation</h1>
        <div className="rot-head-right">
          <span className="rot-stamp mono">{relativeAge(cachedAt, stamp)}</span>
          <button
            className={`rot-refresh ${loading ? "spinning" : ""}`}
            onClick={onRefresh}
            disabled={loading}
            title="Fetch fresh data"
          >
            <i className="ti ti-refresh" />
            {loading ? "Fetching…" : "Refresh"}
          </button>
        </div>
      </div>

      {volume && <VolumePanel volume={volume} />}

      <div className="rot-span">
        <span className="label">span</span>
        <span className="mono span-range">
          {start} → {end}
        </span>
        <span className="mono span-sessions">
          {sessions} {sessions === 1 ? "session" : "sessions"}
        </span>
      </div>

      <div className="rot-layout">
        <table className="rot-table">
          <thead>
            <tr>
              <th className="c-rank">#</th>
              <th className="c-etf">etf</th>
              <th className="c-name">sector</th>
              <th className="c-num">span</th>
              <th className="c-bd">breadth</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const f = r.breadth ? r.breadth.up / r.breadth.total : null;
              const bq =
                f === null ? "" : f >= 0.66 ? "broad" : f >= 0.34 ? "mixed" : "narrow";
              return (
                <tr
                  key={r.etf}
                  className={`clickable ${r.etf === emphasis ? "lit" : ""}`}
                  onClick={() => onOpen(r.etf)}
                  onMouseEnter={() => setEmphasis(r.etf)}
                  onMouseLeave={() => setEmphasis(null)}
                >
                  <td className="c-rank rank">{i + 1}</td>
                  <td className="c-etf tick">{r.etf}</td>
                  <td className="c-name name">{r.name}</td>
                  <td className={`c-num ${dirClass(r.span)}`}>{pct(r.span)}</td>
                  <td className="c-bd">
                    {r.breadth ? (
                      <span className={`bd ${bq}`}>
                        {r.breadth.up}/{r.breadth.total}
                      </span>
                    ) : (
                      <span className="bd flat">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
            {spySpan !== null && (
              <tr
                className="spy"
                onMouseEnter={() => setEmphasis("SPY")}
                onMouseLeave={() => setEmphasis(null)}
              >
                <td colSpan={3} className="name">
                  SPY · benchmark
                </td>
                <td className="c-num">{pct(spySpan)}</td>
                <td />
              </tr>
            )}
          </tbody>
        </table>

        <Calendar
          tradingDates={allDates}
          start={start}
          end={end}
          onChange={onRange}
        />
      </div>

      <SectorPaths
        data={data}
        rows={rows}
        allDates={allDates}
        start={start}
        end={end}
        sessions={sessions}
        emphasis={emphasis}
        onEmphasis={setEmphasis}
      />

      <p className="rot-foot">Click a sector to see its holdings · pick any two dates to recompute the span · hover a row or chip to isolate its path.</p>
    </>
  );
}

function HoldingsTable({
  data,
  etf,
  start,
  end,
  onOpen,
}: {
  data: RotationPayload;
  etf: string;
  start: string;
  end: string;
  onOpen: (ticker: string) => void;
}) {
  const holds = data.sectors[etf]?.holdings || [];
  const rows = holds
    .map((t) => ({ t, span: spanReturn(data, t, start, end) }))
    .filter((r) => r.span !== null)
    .sort((a, b) => (b.span as number) - (a.span as number));

  return (
    <>
      <div className="rot-head">
        <h1>
          {etf} <span className="sub">{data.sectors[etf]?.name}</span>
        </h1>
        <span className="rot-stamp mono">{holds.length} holdings</span>
      </div>
      <table className="rot-table">
        <thead>
          <tr>
            <th className="c-etf">ticker</th>
            <th className="c-num">span</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.t} className="clickable" onClick={() => onOpen(r.t)}>
              <td className="c-etf tick">{r.t}</td>
              <td className={`c-num ${dirClass(r.span as number)}`}>
                {pct(r.span as number)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="rot-foot">Click a ticker to see its level map.</p>
    </>
  );
}
