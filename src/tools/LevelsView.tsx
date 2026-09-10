import { useEffect, useState } from "react";
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

const THRESHOLDS = [1, 1.5, 2, 3];

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

export function LevelsView() {
  const [universe, setUniverse] = useState<Record<string, UniverseSector>>({});
  const [selectedSectors, setSelectedSectors] = useState<Set<string>>(new Set());
  const [threshold, setThreshold] = useState(2);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [cachedAt, setCachedAt] = useState<number | null>(null);
  const [scanning, setScanning] = useState(false);
  const [openTicker, setOpenTicker] = useState<string | null>(null);

  // Load universe + any cached full-universe scan on mount.
  useEffect(() => {
    fetchUniverse().then(setUniverse).catch(() => {});
    fetchCachedScan().then((c) => {
      if (c.result) {
        setResult(c.result);
        setCachedAt(c.cached_at);
        if (c.threshold) setThreshold(c.threshold);
      }
    });
  }, []);

  async function scan() {
    setScanning(true);
    try {
      const sectors = selectedSectors.size ? Array.from(selectedSectors) : undefined;
      const r = await runProximityScan({ sectors, threshold });
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

  if (openTicker) {
    return (
      <div className="rot">
        <LevelLadder
          ticker={openTicker}
          onBack={() => setOpenTicker(null)}
          backLabel="Scan"
        />
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
          <span className="label">within</span>
          <div className="lev-threshold">
            {THRESHOLDS.map((t) => (
              <button
                key={t}
                className={`lev-thresh ${threshold === t ? "on" : ""}`}
                onClick={() => setThreshold(t)}
              >
                {t}%
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
          Nothing within {threshold}% of a level right now
          {selectedSectors.size ? " in the selected sectors" : ""}. Try a wider
          threshold.
        </p>
      ) : (
        <>
          <div className="rot-span">
            <span className="mono span-sessions">
              {result.scanned} scanned · {result.hits} near a level
            </span>
          </div>
          <table className="rot-table">
            <thead>
              <tr>
                <th className="c-etf">ticker</th>
                <th className="c-num">price</th>
                <th className="c-num">level</th>
                <th className="c-num">dist</th>
                <th className="c-bd">side</th>
                <th className="c-bd">touches</th>
                <th className="c-bd">flip</th>
              </tr>
            </thead>
            <tbody>
              {result.rows.map((r, i) => (
                <ScanRowView key={`${r.ticker}-${i}`} row={r} onOpen={() => setOpenTicker(r.ticker)} />
              ))}
            </tbody>
          </table>
          <p className="rot-foot">
            Sorted closest-to-level first · click a row for the full level ladder ·
            <span style={{ color: "var(--up)" }}> ▬</span> at/above support ·
            <span style={{ color: "var(--down)" }}> ▬</span> at/below resistance.
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
  return (
    <tr className="clickable" onClick={onOpen}>
      <td className="c-etf tick">{row.ticker}</td>
      <td className="c-num center">{row.price.toFixed(2)}</td>
      <td className="c-num center">
        {row.lo === row.hi
          ? row.level.toFixed(2)
          : `${row.lo.toFixed(2)}–${row.hi.toFixed(2)}`}
      </td>
      <td className={`c-num ${dirClass}`}>
        {(row.dist_pct >= 0 ? "+" : "") + row.dist_pct.toFixed(2)}%
      </td>
      <td className="c-bd">
        <span className={`lev-side ${dirClass}`}>{row.side}</span>
      </td>
      <td className={`c-bd ${row.touches >= 4 ? "touch-hi" : ""}`}>{row.touches}</td>
      <td className="c-bd">{row.two_sided && <span className="flip">FLIP</span>}</td>
    </tr>
  );
}
