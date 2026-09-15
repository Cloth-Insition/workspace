"""
Migration 002 — add content_hash to tombstones. Reversible, idempotent.

The resurrection guard in save_trades needs to tell two cases apart when an
incoming trade id matches a tombstone:

  * a stale frontend array re-inserting a trade that was deleted on the
    other machine (content identical to what was deleted) -> block
  * the user deliberately re-logging a trade that happens to reuse the same
    ticker-date id (content differs) -> allow, clear the tombstone

So deletions record a canonical content hash of the row they removed.
The column is nullable; lists tombstones don't use the guard and store NULL.

Run against both state databases (the migration syncs to the cloud from the
synced one on its next push):

    python scripts/migrate_002_tombstone_hash.py --db src-python/engine/workspace.db
    (and via the app venv for the synced file, which is libsql-managed)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIVE_DB = REPO / "src-python" / "engine" / "workspace.db"
MIGRATION_NAME = "002_tombstone_hash"


def get_conn(path: Path, use_libsql: bool):
    if use_libsql:
        # The synced database file must ONLY ever be opened through a synced
        # connection: a plain local open writes changes the replication layer
        # never tracks, silently diverging local from cloud (learned the hard
        # way — sync even reports OK afterwards). Credentials come from the
        # environment / src-python/.env via engine.db.
        sys.path.insert(0, str(REPO / "src-python"))
        from engine import db as engine_db
        engine_db._load_env()
        import libsql
        import os
        conn = libsql.connect(
            str(path),
            sync_url=os.environ["TURSO_DATABASE_URL"],
            auth_token=os.environ["TURSO_AUTH_TOKEN"],
            offline=True,
        )
        conn.sync()  # pull before, push after (caller syncs at the end)
        return conn
    return sqlite3.connect(path)


def has_column(conn, table: str, col: str) -> bool:
    return any(r[1] == col for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall())


def applied(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE name=?", (MIGRATION_NAME,)
    ).fetchone()
    return row is not None


def up(conn) -> None:
    if applied(conn):
        print("already applied — nothing to do")
        return
    if not has_column(conn, "tombstones", "content_hash"):
        conn.execute("ALTER TABLE tombstones ADD COLUMN content_hash TEXT")
    conn.execute(
        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
        (MIGRATION_NAME, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"),
    )
    conn.commit()
    print("up: done")


def down(conn) -> None:
    if not applied(conn):
        print("not applied — nothing to undo")
        return
    if has_column(conn, "tombstones", "content_hash"):
        conn.execute("ALTER TABLE tombstones DROP COLUMN content_hash")
    conn.execute("DELETE FROM schema_migrations WHERE name=?", (MIGRATION_NAME,))
    conn.commit()
    print("down: done")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=LIVE_DB)
    ap.add_argument("--down", action="store_true")
    ap.add_argument("--libsql", action="store_true",
                    help="open via libsql (required for the synced database file)")
    args = ap.parse_args()
    if not args.db.exists():
        print(f"database not found: {args.db}")
        return 1
    print(f"target: {args.db}")
    conn = get_conn(args.db, args.libsql)
    try:
        down(conn) if args.down else up(conn)
        if args.libsql:
            conn.sync()  # push the schema change to the cloud
            print("pushed to cloud")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
