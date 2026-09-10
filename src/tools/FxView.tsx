import { useEffect, useRef, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  fetchFxSeries,
  FX_RANGE_KEYS,
  type FxPayload,
  type FxRangeKey,
} from "../lib/api";
import "../styles/fx.css";

/**
 * USD/CHF rate, straight from engine.fx.
 *
 * The pair is CHF=X — francs per 1 dollar — so DOWN is the bad direction for a
 * USD account: the same dollars buy fewer francs. That inversion is the whole
 * reason this tab exists, so it's stated in the caption rather than left for
 * the reader to work out from the axis.
 *
 * The line itself stays neutral. Colouring a whole rate line green or clay
 * would put the loudest thing on screen in permanent service of a direction
 * that only matters at the endpoints; the summary change number carries the
 * up/down tint instead.
 */

const DEFAULT_RANGE: FxRangeKey = "6M";

// Rates sit near 0.80 and move in the third decimal — four places on the axis,
// five in the tooltip where the precision is actually readable.
function fmtRate(v: number, places = 4): string {
  return v.toFixed(places);
}
function fmtSigned(v: number, places = 4): string {
  return (v >= 0 ? "+" : "") + v.toFixed(places);
}
function fmtPct(v: number): string {
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
}
function dirClass(v: number): string {
  return v >= 0 ? "up" : "down";
}

/** Axis/tooltip label. Intraday stamps are ISO with an offset; date-only ranges
 *  are already "YYYY-MM-DD". Keep it short — the range button says the rest. */
function tickLabel(t: string, intraday: boolean): string {
  if (intraday) {
    const d = new Date(t);
    if (!isNaN(d.getTime())) {
      return `${String(d.getDate()).padStart(2, "0")}.${String(
        d.getMonth() + 1
      ).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(
        d.getMinutes()
      ).padStart(2, "0")}`;
    }
    return t;
  }
  return t.slice(2); // "25-08-21"
}

function fullLabel(t: string, intraday: boolean, tz: string | null): string {
  if (!intraday) return t;
  const d = new Date(t);
  if (isNaN(d.getTime())) return t;
  const stamp = d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  return tz ? `${stamp} · ${tz.split("/")[1] ?? tz}` : stamp;
}

function FxTooltip({
  active,
  payload,
  intraday,
  tz,
}: {
  active?: boolean;
  payload?: { payload: { t: string; rate: number } }[];
  intraday: boolean;
  tz: string | null;
}) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div className="fx-tip">
      <span className="fx-tip-rate mono">{fmtRate(p.rate, 5)}</span>
      <span className="fx-tip-when mono">{fullLabel(p.t, intraday, tz)}</span>
    </div>
  );
}

export function FxView() {
  const [range, setRange] = useState<FxRangeKey>(DEFAULT_RANGE);
  const [data, setData] = useState<FxPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Guards against a slow earlier range resolving after a faster later one and
  // painting the chart with the wrong window.
  const reqRef = useRef(0);

  useEffect(() => {
    const seq = ++reqRef.current;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchFxSeries({ range })
      .then((p) => {
        if (cancelled || seq !== reqRef.current) return;
        setData(p);
      })
      .catch((e) => {
        if (cancelled || seq !== reqRef.current) return;
        // Fail loudly — an empty chart that looks like "flat" would be a lie.
        setError(String(e instanceof Error ? e.message : e));
        setData(null);
      })
      .finally(() => {
        if (!cancelled && seq === reqRef.current) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range]);

  const s = data?.summary;

  return (
    <div className="fx">
      <div className="fx-head">
        <h1>
          {data?.label ?? "USD/CHF"}{" "}
          <span className="sub">{data?.pair ?? "CHF=X"}</span>
        </h1>
        <div className="fx-head-right">
          {data?.cached && <span className="fx-cached mono">cached</span>}
          <span className="fx-interval mono">
            {data ? `${data.interval} bars` : ""}
          </span>
        </div>
      </div>

      <div className="fx-ranges">
        {FX_RANGE_KEYS.map((k) => (
          <button
            key={k}
            className={`fx-range ${k === range ? "active" : ""}`}
            onClick={() => setRange(k)}
            disabled={loading && k === range}
          >
            {k}
          </button>
        ))}
      </div>

      {s && (
        <div className="fx-summary">
          <div className="fx-stat fx-stat-lead">
            <span className="fx-stat-label">rate</span>
            <span className="fx-stat-value mono">{fmtRate(s.last, 5)}</span>
          </div>
          <div className="fx-stat">
            <span className="fx-stat-label">change</span>
            <span className={`fx-stat-value mono ${dirClass(s.change)}`}>
              {fmtSigned(s.change)}
            </span>
          </div>
          <div className="fx-stat">
            <span className="fx-stat-label">%</span>
            <span className={`fx-stat-value mono ${dirClass(s.change_pct)}`}>
              {fmtPct(s.change_pct)}
            </span>
          </div>
          <div className="fx-stat">
            <span className="fx-stat-label">high</span>
            <span className="fx-stat-value mono">{fmtRate(s.high)}</span>
          </div>
          <div className="fx-stat">
            <span className="fx-stat-label">low</span>
            <span className="fx-stat-value mono">{fmtRate(s.low)}</span>
          </div>
        </div>
      )}

      <div className="fx-panel">
        {error && <div className="fx-msg fx-err">{error}</div>}
        {!error && !data && loading && (
          <div className="fx-msg">Fetching rate history…</div>
        )}
        {!error && data && (
          <>
            <div className={`fx-chart ${loading ? "stale" : ""}`}>
              <ResponsiveContainer width="100%" height={340}>
                <LineChart
                  data={data.points}
                  margin={{ top: 8, right: 8, bottom: 4, left: 4 }}
                >
                  <CartesianGrid
                    stroke="var(--line-faint)"
                    strokeDasharray="0"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="t"
                    tickFormatter={(t: string) => tickLabel(t, data.intraday)}
                    stroke="var(--line)"
                    tick={{ fill: "var(--text-2)", fontSize: 10 }}
                    tickLine={false}
                    minTickGap={44}
                  />
                  <YAxis
                    // An FX rate near 0.80 has no meaningful zero — a
                    // zero-based axis would flatten every move worth seeing.
                    domain={["auto", "auto"]}
                    tickFormatter={(v: number) => fmtRate(v)}
                    stroke="var(--line)"
                    tick={{ fill: "var(--text-2)", fontSize: 10 }}
                    tickLine={false}
                    width={58}
                  />
                  <Tooltip
                    content={
                      <FxTooltip intraday={data.intraday} tz={data.tz} />
                    }
                    cursor={{ stroke: "var(--line)", strokeWidth: 1 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="rate"
                    stroke="var(--text-1)"
                    strokeWidth={1.4}
                    dot={false}
                    activeDot={{
                      r: 3,
                      fill: "var(--accent)",
                      stroke: "var(--bg-1)",
                      strokeWidth: 1.5,
                    }}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="fx-foot">
              <span className="fx-note">
                Francs per dollar — the line falling means your dollars buy
                fewer francs.
              </span>
              <span className="fx-asof mono">
                {s?.count ?? 0} points
                {s?.as_of ? ` · ${fullLabel(s.as_of, data.intraday, data.tz)}` : ""}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
