import type { SyncStatus } from "./lib/api";

export type ToolId = "rotation" | "levels" | "ledger" | "lists" | "luck" | "fx";

interface Tool {
  id: ToolId;
  label: string;
  icon: string; // Tabler icon class suffix
}

const TOOLS: Tool[] = [
  { id: "rotation", label: "Rotation", icon: "arrows-sort" },
  { id: "levels", label: "Levels", icon: "ruler-2" },
  { id: "ledger", label: "Ledger", icon: "book" },
  { id: "luck", label: "Luck Check", icon: "dice" },
  { id: "fx", label: "USD/CHF", icon: "currency-franc" },
  { id: "lists", label: "Lists", icon: "checkbox" },
];

function ago(unixSeconds: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000) - unixSeconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// The failure mode that matters is trusting a stale journal: anything that
// isn't a recent successful sync must be visibly "unsynced", never quietly
// green. Stale = last attempt errored, never synced, or last success is
// older than ~2.5 background intervals.
function syncView(sync: SyncStatus): { state: "ok" | "stale"; label: string; detail: string } {
  const staleAfter = (sync.interval_seconds ?? 300) * 2.5;
  const age = sync.last_ok_at ? Date.now() / 1000 - sync.last_ok_at : Infinity;
  const stale = sync.last_error !== null || sync.last_ok_at === null || age > staleAfter;
  if (!stale) {
    return {
      state: "ok",
      label: `synced ${ago(sync.last_ok_at!)}`,
      detail: "State is replicating to Turso. Click to sync now.",
    };
  }
  const since = sync.last_ok_at ? `last sync ${ago(sync.last_ok_at)}` : "never synced";
  return {
    state: "stale",
    label: `unsynced · ${since}`,
    detail:
      (sync.last_error ? `Sync failing: ${sync.last_error}\n` : "") +
      (sync.pending_changes > 0
        ? `${sync.pending_changes} local change(s) not yet pushed.\n`
        : "") +
      "Working on the local copy; changes reconcile when the network returns. Click to retry.",
  };
}

export function Sidebar({
  active,
  onSelect,
  ready,
  sync,
  onSyncNow,
}: {
  active: ToolId;
  onSelect: (id: ToolId) => void;
  ready: boolean | null;
  sync: SyncStatus | null;
  onSyncNow: () => void;
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-mark">
        <span className={`mark-dot ${ready ? "live" : ""}`} />
        <span className="mark-label">workspace</span>
      </div>

      <nav className="sidebar-nav">
        {TOOLS.map((t) => (
          <button
            key={t.id}
            className={`nav-item ${active === t.id ? "active" : ""}`}
            onClick={() => onSelect(t.id)}
          >
            <i className={`ti ti-${t.icon}`} aria-hidden="true" />
            {t.label}
          </button>
        ))}
      </nav>

      <button className="nav-item nav-new" onClick={() => onSelect("lists")}>
        <i className="ti ti-plus" aria-hidden="true" />
        New list
      </button>

      {sync !== null &&
        (sync.mode === "local" ? (
          <div className="sidebar-sync" title="No sync credentials configured — this machine only.">
            <span className="sync-dot local" />
            <span className="sync-label">local only</span>
          </div>
        ) : (
          (() => {
            const v = syncView(sync);
            return (
              <button
                className={`sidebar-sync clickable ${v.state}`}
                title={v.detail}
                onClick={onSyncNow}
              >
                <span className={`sync-dot ${v.state}`} />
                <span className="sync-label">{v.label}</span>
              </button>
            );
          })()
        ))}
    </aside>
  );
}
