import { useEffect, useState } from "react";
import {
  getLists,
  addList,
  renameList,
  deleteList,
  addItem,
  updateItem,
  deleteItem,
  type TodoList,
  type ListItem,
} from "../lib/listsApi";
import "../styles/lists.css";

export function ListsView() {
  const [lists, setLists] = useState<TodoList[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh(selectId?: string) {
    const data = await getLists();
    setLists(data);
    setActiveId((cur) => selectId ?? cur ?? (data[0]?.id || null));
    setLoading(false);
  }

  useEffect(() => {
    refresh();
  }, []);

  const active = lists.find((l) => l.id === activeId) || null;

  async function handleAddList() {
    const created = await addList("New list");
    await refresh(created.id);
  }

  if (loading) return <div className="lists-msg">Loading lists…</div>;

  return (
    <div className="lists">
      <aside className="lists-rail">
        <div className="lists-rail-head">
          <span className="lists-rail-title">Lists</span>
          <button className="lists-add-btn" onClick={handleAddList} title="New list">
            <i className="ti ti-plus" />
          </button>
        </div>
        {lists.length === 0 ? (
          <p className="lists-empty-rail">No lists yet. Add one to start.</p>
        ) : (
          <nav className="lists-rail-nav">
            {lists.map((l) => (
              <button
                key={l.id}
                className={`lists-rail-item ${l.id === activeId ? "active" : ""}`}
                onClick={() => setActiveId(l.id)}
              >
                <span className="lists-rail-name">{l.name}</span>
                <span className="lists-rail-count">
                  {l.items.filter((i) => !i.done).length || ""}
                </span>
              </button>
            ))}
          </nav>
        )}
      </aside>

      <section className="lists-pane">
        {active ? (
          <ListDetail
            list={active}
            onChange={() => refresh(active.id)}
            onDeleteList={async () => {
              await deleteList(active.id);
              const remaining = lists.filter((l) => l.id !== active.id);
              await refresh(remaining[0]?.id);
            }}
          />
        ) : (
          <div className="lists-blank">
            <p>Pick a list, or add a new one.</p>
          </div>
        )}
      </section>
    </div>
  );
}

function ListDetail({
  list,
  onChange,
  onDeleteList,
}: {
  list: TodoList;
  onChange: () => void;
  onDeleteList: () => void;
}) {
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(list.name);
  const [newText, setNewText] = useState("");
  const [newNote, setNewNote] = useState("");
  const [showNote, setShowNote] = useState(false);

  useEffect(() => {
    setNameDraft(list.name);
    setEditingName(false);
  }, [list.id, list.name]);

  async function commitName() {
    const trimmed = nameDraft.trim();
    if (trimmed && trimmed !== list.name) await renameList(list.id, trimmed);
    setEditingName(false);
    onChange();
  }

  async function handleAddItem() {
    const t = newText.trim();
    if (!t) return;
    await addItem(list.id, t, newNote.trim());
    setNewText("");
    setNewNote("");
    setShowNote(false);
    onChange();
  }

  const todo = list.items.filter((i) => !i.done);
  const done = list.items.filter((i) => i.done);

  return (
    <>
      <div className="lists-detail-head">
        {editingName ? (
          <input
            className="lists-name-input"
            value={nameDraft}
            autoFocus
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={commitName}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitName();
              if (e.key === "Escape") {
                setNameDraft(list.name);
                setEditingName(false);
              }
            }}
          />
        ) : (
          <h1 className="lists-name" onClick={() => setEditingName(true)} title="Click to rename">
            {list.name}
          </h1>
        )}
        <button className="lists-del-list" onClick={onDeleteList} title="Delete this list">
          <i className="ti ti-trash" />
        </button>
      </div>

      <div className="lists-add-row">
        <input
          className="lists-text-input"
          placeholder="Add an item…"
          value={newText}
          onChange={(e) => setNewText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !showNote) handleAddItem();
          }}
        />
        <button
          className={`lists-note-toggle ${showNote ? "on" : ""}`}
          onClick={() => setShowNote((s) => !s)}
          title="Add a note"
        >
          <i className="ti ti-note" />
        </button>
        <button className="lists-add-item" onClick={handleAddItem}>
          Add
        </button>
      </div>
      {showNote && (
        <textarea
          className="lists-note-input"
          placeholder="Optional note or detail…"
          value={newNote}
          onChange={(e) => setNewNote(e.target.value)}
          rows={2}
        />
      )}

      <div className="lists-items">
        {list.items.length === 0 && (
          <p className="lists-empty">Nothing here yet. Add your first item above.</p>
        )}

        {todo.map((item) => (
          <Item key={item.id} item={item} onChange={onChange} />
        ))}

        {done.length > 0 && (
          <div className="lists-done-divider">
            <span>Done · {done.length}</span>
          </div>
        )}
        {done.map((item) => (
          <Item key={item.id} item={item} onChange={onChange} />
        ))}
      </div>
    </>
  );
}

function Item({ item, onChange }: { item: ListItem; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(item.text);
  const [note, setNote] = useState(item.note);

  async function toggle() {
    await updateItem(item.id, { done: !item.done });
    onChange();
  }
  async function commit() {
    const t = text.trim();
    if (t && (t !== item.text || note !== item.note)) {
      await updateItem(item.id, { text: t, note });
    }
    setEditing(false);
    onChange();
  }
  async function remove() {
    await deleteItem(item.id);
    onChange();
  }

  return (
    <div className={`lists-item ${item.done ? "done" : ""}`}>
      <button className="lists-check" onClick={toggle} title={item.done ? "Mark not done" : "Mark done"}>
        <i className={item.done ? "ti ti-circle-check-filled" : "ti ti-circle"} />
      </button>

      {editing ? (
        <div className="lists-item-edit">
          <input
            className="lists-text-input"
            value={text}
            autoFocus
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit();
              if (e.key === "Escape") {
                setText(item.text);
                setNote(item.note);
                setEditing(false);
              }
            }}
          />
          <textarea
            className="lists-note-input"
            placeholder="Note…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onBlur={commit}
            rows={2}
          />
        </div>
      ) : (
        <div className="lists-item-body" onClick={() => setEditing(true)}>
          <span className="lists-item-text">{item.text}</span>
          {item.note && <span className="lists-item-note">{item.note}</span>}
        </div>
      )}

      <button className="lists-item-del" onClick={remove} title="Delete item">
        <i className="ti ti-x" />
      </button>
    </div>
  );
}
