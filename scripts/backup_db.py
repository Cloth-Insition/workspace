"""
Timestamped backup of a workspace database, with verification.

Uses sqlite3's online backup API, which is safe against a database that is
open in WAL mode by a running sidecar — it copies a consistent snapshot
including un-checkpointed WAL content. A plain file copy is NOT safe and is
exactly the mistake this script exists to prevent.

Usage (from repo root):

    python scripts/backup_db.py                     # the local fallback DB
    python scripts/backup_db.py --cloud             # what Turso holds now
    python scripts/backup_db.py --verify-only path/to/backup.db

--cloud needs the project venv (it uses libsql) and Turso credentials:

    src-python\\.venv\\Scripts\\python scripts\\backup_db.py --cloud

Backups land in backups/ (gitignored) as workspace-YYYYMMDD-HHMMSS.db.
Verification: PRAGMA integrity_check, then per-table row counts AND a
content digest of every row, compared against the source. The script exits
non-zero and deletes the new backup if verification fails.

NEVER point this at a live libSQL synced replica (workspace-synced.db).
Any plain SQLite connection to a replica checkpoints and deletes its WAL
when it closes, after which that replica silently stops syncing in both
directions while still reporting success. The script refuses such files;
--cloud gets the same data safely by pulling a throwaway replica.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIVE_DB = REPO / "src-python" / "engine" / "workspace.db"
BACKUP_DIR = REPO / "backups"


def is_synced_replica(path: Path) -> bool:
    return Path(str(path) + "-info").exists()


def refuse_replica(path: Path) -> None:
    if is_synced_replica(path):
        raise SystemExit(
            f"refusing to open {path}: it is a live libSQL synced replica.\n"
            "Opening it with plain SQLite destroys its sync log and silently\n"
            "breaks syncing. To back up the synced data, use --cloud instead.")


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
        print(f"  {t:<18} {n} rows")

    if against is None:
        return True

    src = sqlite3.connect(f"file:{against.as_posix()}?mode=ro", uri=True)
    try:
        live_snap = snapshot(src)
    finally:
        src.close()

    if backup_snap == live_snap:
        print("content match: backup is identical to its source")
        return True
    for t in sorted(set(backup_snap) | set(live_snap)):
        b, l = backup_snap.get(t), live_snap.get(t)
        if b != l:
            print(f"FAIL: table {t}: backup={b} source={l}")
    return False


def pull_cloud_copy() -> tuple[Path, Path]:
    """Pull a fresh, throwaway replica of the Turso database. Safe to open
    with plain SQLite precisely because it is discarded afterwards."""
    sys.path.insert(0, str(REPO / "src-python"))
    try:
        import libsql
        from engine import db
    except ImportError as exc:
        raise SystemExit(f"--cloud needs the project venv (libsql): {exc}\n"
                         r"run: src-python\.venv\Scripts\python scripts\backup_db.py --cloud")
    if db.mode() != "synced":
        raise SystemExit("--cloud needs Turso credentials in src-python/.env")
    tmp = Path(tempfile.mkdtemp(prefix="cloud-backup-"))
    path = tmp / "cloud.db"
    conn = libsql.connect(str(path), sync_url=os.environ["TURSO_DATABASE_URL"],
                          auth_token=os.environ["TURSO_AUTH_TOKEN"], offline=True)
    conn.sync()
    conn.close()
    print(f"pulled current cloud state into a throwaway replica")
    return tmp, path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=LIVE_DB, help="source database")
    ap.add_argument("--cloud", action="store_true",
                    help="back up what Turso currently holds (needs the venv)")
    ap.add_argument("--out", type=Path, default=BACKUP_DIR, help="backup directory")
    ap.add_argument("--verify-only", type=Path, default=None,
                    help="verify an existing backup file (no new backup taken)")
    args = ap.parse_args()

    if args.verify_only:
        refuse_replica(args.verify_only)
        against = None
        if args.db.exists() and not is_synced_replica(args.db):
            against = args.db
        return 0 if verify(args.verify_only, against) else 1

    tmp = None
    if args.cloud:
        tmp, source = pull_cloud_copy()
    else:
        source = args.db
        refuse_replica(source)
        if not source.exists():
            print(f"FAIL: source database not found: {source}")
            return 1

    try:
        args.out.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        suffix = "-cloud" if args.cloud else ""
        dest = args.out / f"workspace{suffix}-{stamp}.db"

        src = sqlite3.connect(source)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)  # online backup API — WAL-safe
        finally:
            dst.close()
            src.close()
        for side in ("-wal", "-shm"):
            Path(str(dest) + side).unlink(missing_ok=True)
        print(f"backup written: {dest}")

        if verify(dest, source):
            print("BACKUP VERIFIED")
            return 0
        dest.unlink(missing_ok=True)
        print("backup deleted (failed verification)")
        return 1
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
