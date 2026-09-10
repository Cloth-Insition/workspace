import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import {
  fetchRotation,
  fetchCachedRotation,
  type RotationPayload,
} from "./api";

/**
 * Rotation state lives here, above the tab views, so switching tabs no longer
 * unmounts it and forces a refetch. It also reuses the sidecar's cached scan
 * on startup, so an app restart shows data instantly instead of cold-fetching
 * the ~150 tickers (which takes minutes).
 *
 * Drill position and the calendar range live here too, so even where you were
 * in the drill-down survives a tab switch.
 */

type Drill =
  | { level: "sectors" }
  | { level: "holdings"; etf: string }
  | { level: "levels"; etf: string; ticker: string };

interface RotationCtx {
  data: RotationPayload | null;
  loading: boolean;       // a live fetch is in flight
  error: string | null;
  cachedAt: number | null; // unix seconds of the loaded data, or null if live-only
  drill: Drill;
  range: { start: string; end: string } | null;
  setDrill: (d: Drill) => void;
  setRange: (r: { start: string; end: string }) => void;
  refresh: () => Promise<void>; // force a live fetch
}

const Ctx = createContext<RotationCtx | null>(null);

function defaultRange(p: RotationPayload) {
  const dates = Array.from(
    new Set(
      Object.keys(p.sectors).flatMap((etf) =>
        (p.series[etf] || []).map(([d]) => d)
      )
    )
  ).sort();
  if (!dates.length) return null;
  return {
    start: dates[Math.max(0, dates.length - 6)],
    end: dates[dates.length - 1],
  };
}

export function RotationProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<RotationPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cachedAt, setCachedAt] = useState<number | null>(null);
  const [drill, setDrill] = useState<Drill>({ level: "sectors" });
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await fetchRotation();
      if (p.error) setError(p.error);
      setData(p);
      setCachedAt(Math.floor(Date.now() / 1000));
      const r = defaultRange(p);
      if (r) setRange(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // On first mount: try the cache. If a scan is cached, show it instantly and
  // do NOT auto-fetch — the user refreshes when they want fresh numbers. If
  // there's no cache at all, do the initial live fetch.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const cached = await fetchCachedRotation();
      if (cancelled) return;
      if (cached.payload) {
        setData(cached.payload);
        setCachedAt(cached.cached_at);
        const r = defaultRange(cached.payload);
        if (r) setRange(r);
      } else {
        refresh();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  return (
    <Ctx.Provider
      value={{
        data,
        loading,
        error,
        cachedAt,
        drill,
        range,
        setDrill,
        setRange,
        refresh,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useRotation() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useRotation must be used within RotationProvider");
  return ctx;
}
