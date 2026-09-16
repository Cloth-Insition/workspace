// Thin typed client for the Python sidecar.
//
// Everything Python lives behind these calls. The frontend never assumes the
// sidecar is up — useHealth() polls /health on startup so the UI can show a
// clear "starting" state instead of a broken table.

const BASE = "http://127.0.0.1:8765";

export interface VolumeSector {
  etf: string;
  name: string;
  today: number;
  avg20: number;
  rel: number;
}
/** One session in the volume panel: dollar volume plus how the market moved
 *  that day. `up`/`n` are the breadth count (names up out of names counted);
 *  both are null on a session with nothing to compare against. `spy` is SPY's
 *  own percentage change, shown in the tooltip. */
export interface VolumeDay {
  d: string;
  v: number;
  up: number | null;
  n: number | null;
  spy: number | null;
}

export interface VolumeBlock {
  /** Every session fetched — about a year, oldest first. */
  daily?: VolumeDay[];
  /** Older shape, kept only so a scan cached by a previous build still
   *  renders (uncoloured, last 30 sessions) instead of blanking the panel. */
  universe_daily?: [string, number][];
  sectors: VolumeSector[];
  today: string | null;
  today_is_latest: boolean;
}

export interface RotationPayload {
  generated_human: string;
  sectors: Record<string, { name: string; holdings: string[] }>;
  series: Record<string, [string, number][]>;
  volume?: VolumeBlock;
  month_bars: number;
  fetched: number;
  total: number;
  error: string | null;
}

export interface Level extends LevelMetrics {
  lo: number;
  hi: number;
  center: number;
  dist_pct: number;
  touches: number;
  two_sided: boolean;
  first: string;
  last: string;
}

export interface LevelMap {
  ticker: string;
  price: number | null;
  atr?: number | null;
  atr_pct?: number | null;
  levels: Level[];
  error: string | null;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    // FastAPI puts the real reason in `detail` (the FX routes turn an FxError
    // into a 502 that way). Surface it instead of a bare status code.
    let detail = "";
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = ` — ${body.detail}`;
    } catch {
      /* non-JSON error body; the status alone will have to do */
    }
    throw new Error(`${path} failed: ${res.status}${detail}`);
  }
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

// ---- Sync: multi-machine state replication (Turso) ----
//
// mode "local" means no credentials configured — deliberately not syncing.
// In mode "synced", last_ok_at/last_attempt_at are unix seconds and
// last_error carries the most recent failure (cleared on success). The
// sidebar indicator derives staleness from these; a fetch failure returns
// null so a dead sidecar reads as "unknown", not as "synced".

export interface SyncStatus {
  mode: "synced" | "local";
  last_ok_at: number | null;
  last_attempt_at: number | null;
  last_error: string | null;
  pending_changes: number;
  interval_seconds: number | null;
}

export async function fetchSyncStatus(): Promise<SyncStatus | null> {
  try {
    const res = await fetch(`${BASE}/sync/status`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export function triggerSyncNow(): Promise<{
  ok: boolean;
  error: string | null;
  status: SyncStatus;
}> {
  return post("/sync/now", {});
}

export function fetchRotation(period?: string) {
  return post<RotationPayload>("/rotation/scan", { period: period ?? null });
}

export function fetchLevels(ticker: string) {
  return post<LevelMap>("/levels/scan", { ticker });
}

export interface CachedRotation {
  payload: RotationPayload | null;
  cached_at: number | null;
  age_seconds: number | null;
}

export async function fetchCachedRotation(): Promise<CachedRotation> {
  try {
    const res = await fetch(`${BASE}/rotation/cached`);
    if (!res.ok) return { payload: null, cached_at: null, age_seconds: null };
    return res.json();
  } catch {
    return { payload: null, cached_at: null, age_seconds: null };
  }
}

// ---- Levels: proximity scan across the universe ----

/** Everything measured about one level. Detection is unchanged — these
 *  describe levels the scanner already found, from OHLCV it already fetched.
 *  Fields are optional so a scan cached by an older build still renders. */
export interface LevelMetrics {
  /** Distance to the level in ATR — the same setting means the same thing in
   *  a calm market and a fast one, which percent does not. */
  dist_atr?: number | null;
  /** Sessions since the level was last / first touched. */
  bars_since_last?: number;
  bars_since_first?: number;
  /** Volume on the touch bars vs this ticker's own median (1 = typical). */
  touch_vol_rel?: number | null;
  /** Times price has closed clean through the level's band since it formed. */
  traversals?: number;
  /** Is price heading toward this level (direction-aware, so a level price
   *  just broke through counts as left behind, not approached). */
  moving_toward?: boolean | null;
  /** Sessions until price reaches it at the last fortnight's pace; null when
   *  it is moving away. */
  eta_bars?: number | null;
  /** Clear air beyond the level, and the level behind it, in ATR.
   *  room_atr null means nothing beyond it at all — the most room there is. */
  room_atr?: number | null;
  behind_atr?: number | null;
  /** 0-100 blend of the above, with its components. Convenience for ordering,
   *  not a verdict: the weights are unvalidated guesses. */
  score?: number;
  parts?: Record<string, number>;
  atr_pct?: number | null;
}

export interface ScanRow extends LevelMetrics {
  ticker: string;
  price: number;
  level: number;
  lo: number;
  hi: number;
  dist_pct: number;
  side: "above" | "below";
  touches: number;
  two_sided: boolean;
  first: string;
  last: string;
}
export interface ScanResult {
  rows: ScanRow[];
  scanned: number;
  requested: number;
  hits: number;
}
export interface UniverseSector {
  name: string;
  tickers: string[];
}

export async function fetchUniverse(): Promise<Record<string, UniverseSector>> {
  const res = await fetch(`${BASE}/levels/universe`);
  const data = await res.json();
  return data.sectors;
}

export function runProximityScan(opts: {
  sectors?: string[];
  /** Percent distance — still accepted, but the UI now scans in ATR. */
  threshold?: number;
  /** Distance in ATR. When set, the backend measures "near" in ATR instead. */
  thresholdAtr?: number;
  minTouches?: number;
}): Promise<ScanResult> {
  return post<ScanResult>("/levels/proximity", {
    sectors: opts.sectors ?? null,
    threshold: opts.threshold ?? 2.0,
    threshold_atr: opts.thresholdAtr ?? null,
    min_touches: opts.minTouches ?? 2,
  });
}

export interface CachedScan {
  result: ScanResult | null;
  cached_at: number | null;
  age_seconds: number | null;
  threshold: number | null;
  threshold_atr?: number | null;
  min_touches?: number | null;
}
export async function fetchCachedScan(): Promise<CachedScan> {
  try {
    const res = await fetch(`${BASE}/levels/cached`);
    if (!res.ok) return { result: null, cached_at: null, age_seconds: null, threshold: null };
    return res.json();
  } catch {
    return { result: null, cached_at: null, age_seconds: null, threshold: null };
  }
}

// ---- FX: USD/CHF rate history ----
//
// The pair is CHF=X — francs per dollar. A falling line means a USD balance
// buys fewer francs. Rate only; nothing here converts an account value.

export type FxRangeKey = "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "5Y" | "MAX";

export const FX_RANGE_KEYS: FxRangeKey[] = [
  "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX",
];

export interface FxPoint {
  t: string;   // "YYYY-MM-DD", or a tz-aware ISO stamp on intraday ranges
  rate: number;
}

export interface FxSummary {
  first: number;
  last: number;
  change: number;
  change_pct: number;
  high: number;
  low: number;
  count: number;
  as_of: string | null;
}

export interface FxPayload {
  pair: string;
  label: string;
  range: FxRangeKey;
  interval: string;
  intraday: boolean;
  tz: string | null;
  points: FxPoint[];
  summary: FxSummary;
  fetched_at: string;
  cached: boolean;
}

export interface FxRangeSpec {
  key: FxRangeKey;
  period: string;
  interval: string;
}
export interface FxRanges {
  default_pair: string;
  pairs: { symbol: string; label: string }[];
  ranges: FxRangeSpec[];
}

export function fetchFxSeries(opts: {
  pair?: string;
  range?: FxRangeKey;
  interval?: string;
} = {}): Promise<FxPayload> {
  return post<FxPayload>("/fx/series", {
    pair: opts.pair ?? null,
    range: opts.range ?? null,
    interval: opts.interval ?? null,
  });
}

export async function fetchFxRanges(): Promise<FxRanges> {
  const res = await fetch(`${BASE}/fx/ranges`);
  if (!res.ok) throw new Error(`/fx/ranges failed: ${res.status}`);
  return res.json();
}
