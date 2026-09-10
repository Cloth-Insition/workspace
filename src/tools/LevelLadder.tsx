import { useEffect, useState } from "react";
import { fetchLevels, type LevelMap } from "../lib/api";

function pct(n: number) {
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

/**
 * The full S/R level ladder for one ticker. Shared by the rotation drill-down
 * (reached sector → holding → ticker) and the standalone Levels tab (reached by
 * clicking a proximity-scan hit), so a level map looks identical wherever you
 * land on it. `onBack`, when given, renders a back link above the ladder.
 */
export function LevelLadder({
  ticker,
  onBack,
  backLabel = "Back",
}: {
  ticker: string;
  onBack?: () => void;
  backLabel?: string;
}) {
  const [map, setMap] = useState<LevelMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    fetchLevels(ticker)
      .then((m) => {
        if (m.error) setErr(m.error);
        setMap(m);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [ticker]);

  if (loading) return <div className="rot-msg">Computing levels for {ticker}…</div>;
  if (err) return <div className="rot-msg rot-err">{err}</div>;
  if (!map || map.price === null) return null;

  const overhead = map.levels.filter((l) => l.center >= map.price!).length;
  let priceDrawn = false;

  return (
    <>
      {onBack && (
        <div className="crumb">
          <span className="crumb-link" onClick={onBack}>
            {backLabel}
          </span>
          <i className="ti ti-chevron-right" aria-hidden="true" />
          <span className="crumb-here">{ticker}</span>
        </div>
      )}

      <div className="rot-head">
        <h1>
          {ticker} <span className="sub">level map</span>
        </h1>
        <span className="rot-stamp mono">
          {map.levels.length} levels · {overhead} overhead ·{" "}
          {map.levels.length - overhead} below
        </span>
      </div>

      <table className="rot-table ladder">
        <thead>
          <tr>
            <th className="c-etf">zone</th>
            <th className="c-num">center</th>
            <th className="c-num">dist</th>
            <th className="c-bd">touches</th>
            <th className="c-bd">flip</th>
            <th className="c-date">last touch</th>
          </tr>
        </thead>
        <tbody>
          {map.levels.map((lv, i) => {
            const below = lv.center < map.price!;
            const rows = [];
            if (below && !priceDrawn) {
              priceDrawn = true;
              rows.push(
                <tr key="now" className="now">
                  <td className="tick">{map.price!.toFixed(2)}</td>
                  <td colSpan={5}>current price · last close</td>
                </tr>
              );
            }
            rows.push(
              <tr key={i}>
                <td className={`tick zone ${below ? "up" : "down"}`}>
                  {lv.lo === lv.hi
                    ? lv.lo.toFixed(2)
                    : `${lv.lo.toFixed(2)}–${lv.hi.toFixed(2)}`}
                </td>
                <td className="c-num center">{lv.center.toFixed(2)}</td>
                <td className={`c-num ${below ? "up" : "down"}`}>
                  {pct(lv.dist_pct)}
                </td>
                <td className={`c-bd ${lv.touches >= 4 ? "touch-hi" : ""}`}>
                  {lv.touches}
                </td>
                <td className="c-bd">
                  {lv.two_sided && <span className="flip">FLIP</span>}
                </td>
                <td className="c-date date">{lv.last}</td>
              </tr>
            );
            return rows;
          })}
        </tbody>
      </table>

      <p className="rot-foot">
        <span style={{ color: "var(--down)" }}>▬</span> resistance overhead ·{" "}
        <span style={{ color: "var(--up)" }}>▬</span> support below · zone = full
        span of pivot touches, center = mean · draw the zone, not the decimal.
      </p>
    </>
  );
}
