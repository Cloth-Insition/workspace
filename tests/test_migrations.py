"""
Migration tests: correctness, idempotency, reversibility. Fully offline.

Works on throwaway copies of the live workspace.db. Because the live file
already carries both migrations, a pre-migration original is reconstructed
first (002 down, then 001 down) and the up/idempotent/down cycle is proven
against that — so the test stays valid on any machine with any data,
without depending on a backups/ folder.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import importlib

mig1 = importlib.import_module("migrate_001_sync_prep")
mig2 = importlib.import_module("migrate_002_tombstone_hash")

LIVE = REPO / "src-python" / "engine" / "workspace.db"


def snapshot(path: Path) -> tuple:
    """(schema names, per-table content digests) for equality checks."""
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
        tables = [n for t, n, _ in schema if t == "table"]
        digests = {}
        for t in tables:
            acc, n = 0, 0
            for row in conn.execute(f'SELECT * FROM "{t}"'):
                n += 1
                acc ^= int.from_bytes(
                    hashlib.sha256(repr(row).encode()).digest()[:16], "big")
            digests[t] = (n, acc)
        return tuple(schema), digests
    finally:
        conn.close()


def run(fn, path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        fn(conn)
    finally:
        conn.close()


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="migration-test-"))
    try:
        # Reconstruct a pre-migration original.
        original = work / "original.db"
        shutil.copy(LIVE, original)
        run(mig2.down, original)
        run(mig1.down, original)
        schema0, data0 = snapshot(original)
        table_names = {s[1] for s in schema0 if s[0] == "table"}
        assert "schema_migrations" not in table_names, "down did not fully revert"
        assert "tombstones" not in table_names
        print(f"reconstructed pre-migration original ({len(table_names)} tables)")

        # 001: up, idempotent re-up, correctness, down == original.
        db1 = work / "m1.db"
        shutil.copy(original, db1)
        run(mig1.up, db1)
        conn = sqlite3.connect(db1)
        for t in ("trades", "kv", "lists", "list_items"):
            nulls = conn.execute(
                f'SELECT COUNT(*) FROM "{t}" WHERE updated_at IS NULL').fetchone()[0]
            assert nulls == 0, f"{t}: {nulls} NULL updated_at after up"
        trig = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
        assert trig == 8, f"expected 8 triggers, got {trig}"
        conn.close()
        s_up, _ = snapshot(db1)
        run(mig1.up, db1)  # idempotent
        assert snapshot(db1)[0] == s_up, "001 re-up changed the schema"
        run(mig1.down, db1)
        assert snapshot(db1) == (schema0, data0), "001 down != original"
        print("001: up correct (backfill complete, 8 triggers), idempotent, reversible")

        # 002 on top of 001: same cycle.
        db2 = work / "m2.db"
        shutil.copy(original, db2)
        run(mig1.up, db2)
        s_after1 = snapshot(db2)
        run(mig2.up, db2)
        conn = sqlite3.connect(db2)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tombstones)")]
        assert "content_hash" in cols, cols
        names = [r[0] for r in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]
        assert names == ["001_sync_prep", "002_tombstone_hash"], names
        conn.close()
        s_up2 = snapshot(db2)
        run(mig2.up, db2)  # idempotent
        assert snapshot(db2) == s_up2, "002 re-up changed the database"
        run(mig2.down, db2)
        assert snapshot(db2) == s_after1, "002 down != post-001 state"
        run(mig1.down, db2)
        assert snapshot(db2) == (schema0, data0), "full down chain != original"
        print("002: up correct (content_hash present, migrations recorded), "
              "idempotent, reversible; full down chain restores the original")

        print("\nMIGRATION TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
