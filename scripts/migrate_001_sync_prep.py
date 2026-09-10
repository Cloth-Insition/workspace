"""
Migration 001 — sync preparation. Reversible, idempotent, stdlib-only.

Forward (`up`, the default):
  * Adds `updated_at` TEXT to trades, kv, lists, list_items.
    Format: ISO-8601 UTC with milliseconds ('2026-09-10T14:03:22.123Z') —
    lexicographic order == chronological order, which is what last-write-wins
    comparison needs.
  * Backfills per row from the best existing timestamp:
      - trades:     exitDate, else entryDate (at 00:00:00 UTC)
      - lists:      created (unix seconds)
      - list_items: created (unix seconds)
      - kv:         the migration run time — kv has no per-row history.
        Documented deviation; most kv rows are machine-local caches that
        stop syncing in Phase 3 anyway.
  * Creates INSERT/UPDATE triggers per table so every future write stamps
    `updated_at` automatically even before the app code learns about it.
    An UPDATE that explicitly sets `updated_at` wins over the trigger.
  * Creates `tombstones` (table_name, row_id, deleted_at) — deletions must
    leave a marker or a deleted row resurrects from the other replica at
    sync time. (Row wiring happens with the conflict policy phase.)
  * Creates `schema_migrations` and records this migration.

Reverse (`--down`): drops the triggers, the two new tables, and the
`updated_at` columns. Content-identical to the pre-migration database
(verified by the rehearsal in scripts/rehearse rather than trusted).

Identity note: every syncing table already has a stable unique TEXT key
(trades.id, kv.key, lists.id, list_items.id), so no UUID column is added —
existing ids are the sync identity.

Usage:
    python scripts/migrate_001_sync_prep.py --db path/to/copy.db   # rehearse
    python scripts/migrate_001_sync_prep.py                        # live DB
    python scripts/migrate_001_sync_prep.py --down [--db ...]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIVE_DB = REPO / "src-python" / "engine" / "workspace.db"

MIGRATION_NAME = "001_sync_prep"
TS_FMT = "%Y-%m-%dT%H:%M:%fZ"  # sqlite strftime, %f = SS.SSS

# table -> SQL expression producing the backfill value for existing rows
BACKFILL = {
    "trades": "COALESCE(exitDate, entryDate) || 'T00:00:00.000Z'",
    "lists": "COALESCE(strftime('%Y-%m-%dT%H:%M:%S', created, 'unixepoch') || '.000Z', :now)",
    "list_items": "COALESCE(strftime('%Y-%m-%dT%H:%M:%S', created, 'unixepoch') || '.000Z', :now)",
    "kv": ":now",
}
TABLES = list(BACKFILL)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time()*1000)%1000:03d}Z"


def has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r[1] == col for r in conn.execute(f'PRAGMA table_info("{table}")'))


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def applied(conn: sqlite3.Connection) -> bool:
    return has_table(conn, "schema_migrations") and conn.execute(
        "SELECT 1 FROM schema_migrations WHERE name=?", (MIGRATION_NAME,)
    ).fetchone() is not None


def trigger_sql(table: str) -> str:
    stamp = f"strftime('{TS_FMT}', 'now')"
    return f"""
    CREATE TRIGGER IF NOT EXISTS "{table}_updated_at_insert"
    AFTER INSERT ON "{table}"
    WHEN NEW.updated_at IS NULL
    BEGIN
        UPDATE "{table}" SET updated_at = {stamp} WHERE rowid = NEW.rowid;
    END;

    CREATE TRIGGER IF NOT EXISTS "{table}_updated_at_update"
    AFTER UPDATE ON "{table}"
    WHEN NEW.updated_at IS OLD.updated_at OR NEW.updated_at IS NULL
    BEGIN
        UPDATE "{table}" SET updated_at = {stamp} WHERE rowid = NEW.rowid;
    END;
    """


def up(conn: sqlite3.Connection) -> None:
    if applied(conn):
        print("already applied — nothing to do")
        return
    now = now_iso()
    with conn:  # single transaction: all-or-nothing
        for t in TABLES:
            if not has_column(conn, t, "updated_at"):
                conn.execute(f'ALTER TABLE "{t}" ADD COLUMN updated_at TEXT')
            expr = BACKFILL[t].replace(":now", f"'{now}'")
            conn.execute(f'UPDATE "{t}" SET updated_at = {expr} WHERE updated_at IS NULL')
            conn.executescript(trigger_sql(t))
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tombstones (
                   table_name TEXT NOT NULL,
                   row_id     TEXT NOT NULL,
                   deleted_at TEXT NOT NULL,
                   PRIMARY KEY (table_name, row_id)
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   name       TEXT PRIMARY KEY,
                   applied_at TEXT NOT NULL
               )"""
        )
        conn.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
            (MIGRATION_NAME, now),
        )
    # sanity: no NULL updated_at anywhere
    for t in TABLES:
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}" WHERE updated_at IS NULL').fetchone()[0]
        if n:
            raise RuntimeError(f"{t}: {n} rows left with NULL updated_at")
        total, sample = conn.execute(
            f'SELECT COUNT(*), MIN(updated_at) FROM "{t}"'
        ).fetchone()
        print(f"  {t:<12} {total} rows backfilled (earliest: {sample})")
    print("up: done")


def down(conn: sqlite3.Connection) -> None:
    if not applied(conn):
        print("not applied — nothing to undo")
        return
    with conn:
        for t in TABLES:
            conn.execute(f'DROP TRIGGER IF EXISTS "{t}_updated_at_insert"')
            conn.execute(f'DROP TRIGGER IF EXISTS "{t}_updated_at_update"')
            if has_column(conn, t, "updated_at"):
                conn.execute(f'ALTER TABLE "{t}" DROP COLUMN updated_at')
        conn.execute("DROP TABLE IF EXISTS tombstones")
        conn.execute("DELETE FROM schema_migrations WHERE name = ?", (MIGRATION_NAME,))
        # drop the migrations table itself if this was the only entry,
        # returning the schema to its exact pre-migration shape
        if not conn.execute("SELECT 1 FROM schema_migrations LIMIT 1").fetchone():
            conn.execute("DROP TABLE schema_migrations")
    print("down: done")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=LIVE_DB)
    ap.add_argument("--down", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"database not found: {args.db}")
        return 1
    print(f"target: {args.db}")
    conn = sqlite3.connect(args.db)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")  # match app behaviour during DDL
        down(conn) if args.down else up(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
