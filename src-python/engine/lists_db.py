"""
Lists persistence — SQLite.

A self-contained tool: multiple named (renameable) lists, each holding items
that are either want-to-do or done, with text and an optional note. No links
to trades or any other tool — its own little world, exactly as speced.

Shares the same database file as Ledger but in its own tables, so the two
never touch. Reuses Ledger's connection helper to avoid a second connection
to the same file.

Sync note: deletions insert a tombstone (see engine/reconcile.py) so a list
or item deleted on one machine stays deleted after a conflict merge instead
of resurrecting from the other machine's copy. Lists have no bulk-save path
(every mutation is per-row), so no content-hash resurrection guard is
needed here — tombstones carry NULL hashes.
"""

from __future__ import annotations

import time
import uuid

from . import ledger_db


def _conn():
    return ledger_db._connect()


def _init():
    conn = _conn()
    with ledger_db._lock:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lists (
                id        TEXT PRIMARY KEY,
                name      TEXT NOT NULL,
                seq       INTEGER,
                created   INTEGER
            );

            CREATE TABLE IF NOT EXISTS list_items (
                id        TEXT PRIMARY KEY,
                list_id   TEXT NOT NULL,
                text      TEXT NOT NULL,
                note      TEXT,
                done      INTEGER DEFAULT 0,
                seq       INTEGER,
                created   INTEGER,
                FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()


def _now() -> int:
    return int(time.time())


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) \
        + f".{int(time.time()*1000) % 1000:03d}Z"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _tombstone(conn, table: str, row_id: str) -> None:
    conn.execute(
        "INSERT INTO tombstones (table_name, row_id, deleted_at, content_hash) "
        "VALUES (?, ?, ?, NULL) "
        "ON CONFLICT(table_name, row_id) DO UPDATE SET "
        "deleted_at = excluded.deleted_at, content_hash = NULL",
        (table, row_id, _now_iso()),
    )


def get_all() -> dict:
    """Return every list with its items nested, ordered by seq.

    Shape:
      {"lists": [
        {"id","name","items": [{"id","text","note","done"}, ...]}, ...
      ]}
    """
    _init()
    conn = _conn()
    with ledger_db._lock:
        lrows = conn.execute("SELECT * FROM lists ORDER BY seq ASC").fetchall()
        irows = conn.execute("SELECT * FROM list_items ORDER BY seq ASC").fetchall()

    items_by_list: dict[str, list] = {}
    for r in irows:
        items_by_list.setdefault(r["list_id"], []).append({
            "id": r["id"],
            "text": r["text"],
            "note": r["note"] or "",
            "done": bool(r["done"]),
        })

    lists = [{
        "id": r["id"],
        "name": r["name"],
        "items": items_by_list.get(r["id"], []),
    } for r in lrows]

    return {"lists": lists}


def add_list(name: str) -> dict:
    _init()
    conn = _conn()
    lid = _new_id()
    with ledger_db._lock:
        seq_row = conn.execute("SELECT COALESCE(MAX(seq), -1) + 1 AS n FROM lists").fetchone()
        conn.execute(
            "INSERT INTO lists (id, name, seq, created) VALUES (?, ?, ?, ?)",
            (lid, name, seq_row["n"], _now()),
        )
        conn.commit()
    return {"id": lid, "name": name, "items": []}


def rename_list(list_id: str, name: str) -> dict:
    conn = _conn()
    with ledger_db._lock:
        conn.execute("UPDATE lists SET name = ? WHERE id = ?", (name, list_id))
        conn.commit()
    return {"ok": True}


def delete_list(list_id: str) -> dict:
    conn = _conn()
    with ledger_db._lock:
        item_rows = conn.execute(
            "SELECT id FROM list_items WHERE list_id = ?", (list_id,)).fetchall()
        for r in item_rows:
            _tombstone(conn, "list_items", r["id"])
        conn.execute("DELETE FROM list_items WHERE list_id = ?", (list_id,))
        _tombstone(conn, "lists", list_id)
        conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))
        conn.commit()
    return {"ok": True}


def add_item(list_id: str, text: str, note: str = "") -> dict:
    conn = _conn()
    iid = _new_id()
    with ledger_db._lock:
        seq_row = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 AS n FROM list_items WHERE list_id = ?",
            (list_id,),
        ).fetchone()
        conn.execute(
            "INSERT INTO list_items (id, list_id, text, note, done, seq, created) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (iid, list_id, text, note, seq_row["n"], _now()),
        )
        conn.commit()
    return {"id": iid, "text": text, "note": note, "done": False}


def update_item(item_id: str, text: str | None = None,
                note: str | None = None, done: bool | None = None) -> dict:
    conn = _conn()
    sets, vals = [], []
    if text is not None:
        sets.append("text = ?"); vals.append(text)
    if note is not None:
        sets.append("note = ?"); vals.append(note)
    if done is not None:
        sets.append("done = ?"); vals.append(1 if done else 0)
    if not sets:
        return {"ok": True}
    vals.append(item_id)
    with ledger_db._lock:
        conn.execute(f"UPDATE list_items SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
    return {"ok": True}


def delete_item(item_id: str) -> dict:
    conn = _conn()
    with ledger_db._lock:
        _tombstone(conn, "list_items", item_id)
        conn.execute("DELETE FROM list_items WHERE id = ?", (item_id,))
        conn.commit()
    return {"ok": True}
