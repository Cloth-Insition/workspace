import { useEffect, useMemo, useState } from "react";
import {
  fetchUniverse,
  runProximityScan,
  fetchCachedScan,
  type ScanResult,
  type ScanRow,
  type UniverseSector,
} from "../lib/api";
import { LevelLadder } from "./LevelLadder";
import "../styles/rotation.css";
import "../styles/levels.css";

// Distance is measured in ATR, so one setting means the same thing in a calm
// market and a fast one — the adjustment that used to be made by hand every
// morning ("1% when quiet, wider when it's moving") is now the unit itself.
const ATR_THRESHOLDS = [0.25, 0.5, 1, 1.5];
const TOUCH_OPTIONS = [2, 3, 4, 5];

type SortKey = "score" | "dist" | "eta" | "fresh" | "room" | "touches" | "ticker";

const SORTS: { key: SortKey; label: string; hint: string }[] = [
  { key: "score", label: "score", hint: "blended rank — weights are unvalidated, sort elsewhere if you disagree" },
  { key: "dist", label: "dist", hint: "distance to the level, in ATR" },
  { key: "eta", label: "eta", hint: "sessions until price reaches it at its recent pace" },
  { key: "fresh", label: "fresh", hint: "sessions since the level was last touched" },
  { key: "room", label: "room", hint: "clear air beyond the level, in ATR" },
  { key: "touches", label: "touches", hint: "pivots forming the level" },
  { key: "ticker", label: "ticker", hint: "alphabetical" },
];

function relAge(at: number | null): string {
  if (!at) return "";
  const s = Math.floor(Date.now() / 1000) - at;
  if (s < 90) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// Every sort key resolves to "bigger is better" so one comparator serves them
// all. Missing measurements sink rather than float.
function sortValue(r: ScanRow, key: SortKey): number {
  switch (key) {
    case "score": return r.score ?? -1;
    case "dist": return -Math.abs(r.dist_atr ?? Math.abs(r.dist_pct));
    case "eta": return r.eta_bars == null ? -Infinity : -r.eta_bars;
    case "fresh": return r.bars_since_last == null ? -Infinity : -r.bars_since_last;
    case "room": return r.room_atr ?? Infinity;     // null = nothing beyond = clear air
    case "touches": return r.touches;
    case "ticker": return 0;
  }
}

export function LevelsView() {
  const [universe, setUniverse] = useState<Record<string, UniverseSector>>({});
  const [selectedSectors, setSelectedSectors] = useState<Set<string>>(new Set());
  const [thresholdAtr, setThresholdAtr] = useState(0.5);
  const [minTouches, setMinTouches] = useState(2);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [cachedAt, setCachedAt] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  const [openTicker, setOpenTicker] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>("score");

  // Load universe + any cached full-universe scan on mount.
  useEffect(() => {
    fetchUniverse().then(setUniverse).catch(() => {});
    fetchCachedScan().then((c) => {
      if (c.result) {
        setResult(c.result);
        setCachedAt(c.cached_at);
        if (c.threshold_atr) setThresholdAtr(c.threshold_atr);
        if (c.min_touches) setMinTouches(c.min_touches);
      }
    });
  }, []);

  async function scan() {
    setScanning(true);
    try {
      const sectors = selectedSectors.size ? Array.from(selectedSectors) : undefined;
      const r = await runProximityScan({ sectors, thresholdAtr, minTouches });
      setResult(r);
      setCachedAt(sectors ? null : Math.floor(Date.now() / 1000));
    } finally {
      setScanning(false);
    }
  }

  function toggleSector(etf: string) {
    setSelectedSectors((prev) => {
      const next = new Set(prev);
      if (next.has(etf)) next.delete(etf);
      else next.add(etf);
      return next;
    });
  }

  const rows = useMemo(() => {
    if (!result) return [];
    const list = result.rows.slice();
    if (sort === "ticker") return list.sort((a, b) => a.ticker.localeCompare(b.ticker));
    return list.sort((a, b) => sortValue(b, sort) - sortValue(a, sort));
  }, [result, sort]);

  if (openTicker) {
    return (
      <div className="rot">
        <LevelLadder ticker={openTicker} onBack={() => setOpenTicker(null)} backLabel="Scan" />
      </div>
    );
  }

  return (
    <div className="rot">
      <div className="rot-head">
        <h1>Levels scan</h1>
        <div className="rot-head-right">
          {result && (
            <span className="rot-stamp mono">
              {cachedAt ? relAge(cachedAt) : "filtered"} · {result.hits} near
            </span>
          )}
          <button
            className={`rot-refresh ${scanning ? "spinning" : ""}`}
            onClick={scan}
            disabled={scanning}
          >
            <i className="ti ti-radar" />
            {scanning ? "Scanning…" : "Run scan"}
          </button>
        </div>
      </div>

      {/* Controls */}
      <div className="lev-controls">
        <div className="lev-control-row">
          <span className="label" title="Distance in ATR: the same setting in a quiet market and a fast one">
            within
          </span>
          <div className="lev-threshold">
            {ATR_THRESHOLDS.map((t) => (
              <button
                key={t}
                className={`lev-thresh ${thresholdAtr === t ? "on" : ""}`}
                onClick={() => setThresholdAtr(t)}
                title={`${t} ATR of a level`}
              >
                {t} ATR
              </button>
            ))}
          </div>
        </div>

        <div className="lev-control-row">
          <span className="label" title="Pivots required before a cluster counts as a level. Two is a low bar.">
            touches
          </span>
          <div className="lev-threshold">
            {TOUCH_OPTIONS.map((t) => (
              <button
                key={t}
                className={`lev-thresh ${minTouches === t ? "on" : ""}`}
                onClick={() => setMinTouches(t)}
                title={t === 2 ? "loosest: any two pivots within tolerance" : `${t}+ pivots`}
              >
                {t}+
              </button>
            ))}
          </div>
        </div>

        <div className="lev-control-row">
          <span className="label">sectors</span>
          <div className="lev-sectors">
            <button
              className={`lev-sector ${selectedSectors.size === 0 ? "on" : ""}`}
              onClick={() => setSelectedSectors(new Set())}
            >
              All
            </button>
            {Object.keys(universe).map((etf) => (
              <button
                key={etf}
                className={`lev-sector ${selectedSectors.has(etf) ? "on" : ""}`}
                onClick={() => toggleSector(etf)}
                title={universe[etf].name}
              >
                {etf}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Results */}
      {!result ? (
        <p className="rot-foot">
          Run a scan to find names sitting near a level right now. Whole universe
          by default; pick sectors to narrow it.
        </p>
      ) : result.hits === 0 ? (
        <p className="rot-foot">
          Nothing within {thresholdAtr} ATR of a level with {minTouches}+ touches
          {selectedSectors.size ? " in the selected sectors" : ""}. Widen the
          distance or drop the touch requirement.
        </p>
      ) : (
        <>
          <div className="rot-span">
            <span className="mono span-sessions">
              {result.scanned} scanned · {result.hits} near a level
            </span>
            <div className="lev-sortbar">
              <span className="label">sort</span>
              {SORTS.map((s) => (
                <button
                  key={s.key}
                  className={`lev-sort ${sort === s.key ? "on" : ""}`}
                  onClick={() => setSort(s.key)}
                  title={s.hint}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
          <table className="rot-table">
            <thead>
              <tr>
                <th className="c-etf">ticker</th>
                <th className="c-num">price</th>
                <th className="c-num">level</th>
                <th className="c-num">dist</th>
                <th className="c-bd">side</th>
                <th className="c-bd" title="Sessions until price reaches the level at its recent pace. A dash means it is moving away.">eta</th>
                <th className="c-bd" title="Sessions since the level was last touched">fresh</th>
                <th className="c-bd" title="Clear air beyond the level, in ATR (hover a row for the level behind it)">room</th>
                <th className="c-bd">touches</th>
                <th className="c-bd">flip</th>
                <th className="c-bd" title="Blended rank. The weights are guesses until the journal or a backtest earns them.">score</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <ScanRowView
                  key={`${r.ticker}-${r.level}-${i}`}
                  row={r}
                  onOpen={() => setOpenTicker(r.ticker)}
                />
              ))}
            </tbody>
          </table>
          <p className="rot-foot">
            Click a row for the full level ladder ·
            <span style={{ color: "var(--up)" }}> ▬</span> at/above support ·
            <span style={{ color: "var(--down)" }}> ▬</span> at/below resistance ·
            distance in ATR, so it reads the same in calm and fast markets.
          </p>
        </>
      )}
    </div>
  );
}

function ScanRowView({ row, onOpen }: { row: ScanRow; onOpen: () => void }) {
  // "below" means price is below the level → level is resistance overhead (down
  // colour); "above" means price above the level → support beneath (up colour).
  const dirClass = row.side === "above" ? "up" : "down";
  const dist =
    row.dist_atr != null
      ? `${row.dist_atr >= 0 ? "+" : ""}${row.dist_atr.toFixed(2)}`
      : `${row.dist_pct >= 0 ? "+" : ""}${row.dist_pct.toFixed(2)}%`;
  const eta = row.eta_bars;
  const fresh = row.bars_since_last;

  return (
    <tr className="clickable" onClick={onOpen}>
      <td className="c-etf tick">{row.ticker}</td>
      <td className="c-num center">{row.price.toFixed(2)}</td>
      <td className="c-num center">
        {row.lo === row.hi ? row.level.toFixed(2) : `${row.lo.toFixed(2)}–${row.hi.toFixed(2)}`}
      </td>
      <td
        className={`c-num ${dirClass}`}
        title={`${row.dist_pct >= 0 ? "+" : ""}${row.dist_pct.toFixed(2)}% away`}
      >
        {dist}
      </td>
      <td className="c-bd">
        <span className={`lev-side ${dirClass}`}>{row.side}</span>
      </td>
      <td
        className={`c-bd ${eta != null && eta <= 3 ? "eta-soon" : ""}`}
        title={
          eta == null
            ? "price is moving away from this level"
            : `about ${eta} sessions away at its recent pace`
        }
      >
        {eta == null ? "—" : eta.toFixed(1)}
      </td>
      <td
        className={`c-bd ${fresh != null && fresh <= 10 ? "fresh-hi" : ""}`}
        title={fresh == null ? "" : `last touched ${fresh} sessions ago`}
      >
        {fresh == null ? "—" : `${fresh}b`}
      </td>
      <td
        className="c-bd"
        title={
          !("room_atr" in row)
            ? "not measured — rescan to fill this in"
            : row.room_atr == null
              ? "nothing beyond this level — clear air"
              : `${row.room_atr} ATR beyond` +
                (row.behind_atr != null ? `, ${row.behind_atr} ATR back to the level behind` : "")
        }
      >
        {/* A scan from before these measurements existed has no field at all;
            null means measured and genuinely nothing beyond. Not the same. */}
        {!("room_atr" in row) ? "—" : row.room_atr == null ? "clear" : row.room_atr.toFixed(1)}
      </td>
      <td className={`c-bd ${row.touches >= 4 ? "touch-hi" : ""}`}>{row.touches}</td>
      <td className="c-bd">{row.two_sided && <span className="flip">FLIP</span>}</td>
      <td className="c-bd">
        {row.score == null ? (
          "—"
        ) : (
          <span className={`lev-score ${row.score >= 60 ? "hi" : ""}`}>{row.score}</span>
        )}
      </td>
    </tr>
  );
}
