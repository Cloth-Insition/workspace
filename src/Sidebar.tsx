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

export function Sidebar({
  active,
  onSelect,
  ready,
}: {
  active: ToolId;
  onSelect: (id: ToolId) => void;
  ready: boolean | null;
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
    </aside>
  );
}
