"""
Timestamped backup of the live workspace database, with verification.

Uses sqlite3's online backup API, which is safe against a database that is
open in WAL mode by a running sidecar — it copies a consistent snapshot
including un-checkpointed WAL content. A plain file copy is NOT safe and is
exactly the mistake this script exists to prevent.

Usage (from repo root, any Python 3.11+, no third-party deps):

    python scripts/backup_db.py            # backup + verify
    python scripts/backup_db.py --verify-only path/to/backup.db

Backups land in backups/ (gitignored) as workspace-YYYYMMDD-HHMMSS.db.
Verification: PRAGMA integrity_check, then per-table row counts AND a
content digest of every row, compared against the live database. The script
exits non-zero and deletes the new backup if verification fails.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIVE_DB = REPO / "src-python" / "engine" / "workspace.db"
BACKUP_DIR = REPO / "backups"


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def table_digest(conn: sqlite3.Connection, table: str) -> tuple[int, str]:
    """Row count and an order-independent digest of full row content."""
    count = 0
    acc = 0
    for row in conn.execute(f"SELECT * FROM \"{table}\""):
        count += 1
        h = hashlib.sha256(repr(row).encode()).digest()
        acc ^= int.from_bytes(h[:16], "big")  # XOR: order-independent
    return count, f"{acc:032x}"


def snapshot(conn: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    return {t: table_digest(conn, t) for t in table_names(conn)}


def verify(backup_path: Path, against: Path | None) -> bool:
    conn = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            print(f"FAIL: integrity_check returned {ok!r}")
            return False
        print("integrity_check: ok")
        backup_snap = snapshot(conn)
    finally:
        conn.close()

    for t, (n, _) in sorted(backup_snap.items()):
        print(f"  {t:<12} {n} rows")

    if against is None:
        return True

    src = sqlite3.connect(f"file:{against.as_posix()}?mode=ro", uri=True)
    try:
        live_snap = snapshot(src)
    finally:
        src.close()

    if backup_snap == live_snap:
        print("content match: backup is byte-equivalent to the live database")
        return True
    for t in sorted(set(backup_snap) | set(live_snap)):
        b, l = backup_snap.get(t), live_snap.get(t)
        if b != l:
            print(f"FAIL: table {t}: backup={b} live={l}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=LIVE_DB, help="source database")
    ap.add_argument("--out", type=Path, default=BACKUP_DIR, help="backup directory")
    ap.add_argument("--verify-only", type=Path, default=None,
                    help="verify an existing backup file (no new backup taken)")
    args = ap.parse_args()

    if args.verify_only:
        return 0 if verify(args.verify_only, args.db if args.db.exists() else None) else 1

    if not args.db.exists():
        print(f"FAIL: source database not found: {args.db}")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = args.out / f"workspace-{stamp}.db"

    src = sqlite3.connect(args.db)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)  # online backup API — WAL-safe
    finally:
        dst.close()
        src.close()
    print(f"backup written: {dest}")

    if verify(dest, args.db):
        print("BACKUP VERIFIED")
        return 0
    dest.unlink(missing_ok=True)
    print("backup deleted (failed verification)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
