"""
One-time seed: copy state from the plain-SQLite workspace.db into a fresh
libSQL synced database and push it to Turso.

Why a separate file instead of letting libSQL adopt workspace.db: adopting
an existing database is exactly where libsql's known sync-corruption issues
live. Rows are copied through SQL into a file libSQL created and manages;
workspace.db is opened read-only and stays behind untouched as the
fallback/rollback copy.

What it copies: every table except the machine-local cache keys of kv
(rotation:/levels:/ledger:spy_cache — those belong to the never-synced
cache store; the app migrates them out on next launch anyway).
updated_at values are preserved exactly (the auto-stamp triggers only fire
when updated_at is NULL).

Safety rails:
  * refuses to run if the synced file already exists locally
  * refuses to run if the cloud database already contains trades
    (a spike/ leftover table from Phase 0.5 testing is dropped silently)
  * verifies by pulling a second, throwaway replica and comparing per-table
    row counts and content digests against the source

Run on the desktop (the machine with the data), venv python, network up:

    .venv/Scripts/python ../scripts/seed_synced_db.py

The laptop never runs this — it just starts the app, which pulls.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src-python"))
from engine import db  # noqa: E402  (env + path logic lives there)

SOURCE = Path(__file__).resolve().parent.parent / "src-python" / "engine" / "workspace.db"


def digest_tables(conn, tables: list[str]) -> dict[str, tuple[int, str]]:
    out = {}
    for t in tables:
        count, acc = 0, 0
        for row in conn.execute(f'SELECT * FROM "{t}"').fetchall():
            count += 1
            h = hashlib.sha256(repr(tuple(row)).encode()).digest()
            acc ^= int.from_bytes(h[:16], "big")
        out[t] = (count, f"{acc:032x}")
    return out


def main() -> int:
    if db.mode() != "synced":
        print("No Turso credentials configured (src-python/.env) — nothing to seed against.")
        return 1
    if not SOURCE.exists():
        print(f"source database not found: {SOURCE}")
        return 1
    target = db.state_db_path()
    if target.exists():
        print(f"refusing: synced database already exists at {target}\n"
              "If you intend to re-seed, delete it (and its -wal/-shm/-info "
              "siblings) and wipe the Turso database first.")
        return 1

    import libsql

    src = sqlite3.connect(f"file:{SOURCE.as_posix()}?mode=ro", uri=True)

    # Sanity: migration 001 must be applied to the source.
    has_mig = src.execute(
        "SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone()
    if not has_mig:
        print("refusing: source has no schema_migrations — run migrate_001 first")
        return 1

    tables = [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    print(f"source tables: {tables}")

    url, token = os.environ["TURSO_DATABASE_URL"], os.environ["TURSO_AUTH_TOKEN"]
    dst = libsql.connect(str(target), sync_url=url, auth_token=token, offline=True)
    dst.sync()  # pull current cloud state
    # libsql enforces foreign keys by default (stdlib sqlite3 does not);
    # tables are copied in name order, so disable enforcement for the copy.
    dst.execute("PRAGMA foreign_keys=OFF")

    # Refuse a non-empty cloud DB (spike leftovers excepted).
    existing = [r[0] for r in dst.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    for t in existing:
        if t == "spike":
            dst.execute("DROP TABLE spike")
            dst.commit()
            print("dropped Phase-0.5 spike table from cloud DB")
        else:
            print(f"refusing: cloud database already contains table {t!r}.\n"
                  "Seed expects an empty Turso database. Wipe it in the "
                  "dashboard (or create a fresh one) and rerun.")
            return 1

    # Schema first (tables, then triggers), then rows.
    for kind in ("table", "trigger"):
        for (ddl,) in src.execute(
            "SELECT sql FROM sqlite_master WHERE type=? AND sql IS NOT NULL "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name", (kind,)):
            dst.execute(ddl)
    for t in tables:
        cols = [r[1] for r in src.execute(f'PRAGMA table_info("{t}")')]
        col_list = ", ".join(f'"{c}"' for c in cols)
        rows = src.execute(f'SELECT {col_list} FROM "{t}"').fetchall()
        skipped = 0
        if t == "kv":
            keep = [r for r in rows if not db.is_local_only_key(r[0])]
            skipped = len(rows) - len(keep)
            rows = keep
        if rows:
            dst.executemany(
                f'INSERT INTO "{t}" ({col_list}) VALUES ({", ".join("?"*len(cols))})',
                [tuple(r) for r in rows])
        note = f" (skipped {skipped} machine-local cache keys)" if skipped else ""
        print(f"  {t:<18} {len(rows)} rows copied{note}")
    dst.commit()
    dst.sync()  # push
    print("pushed to Turso")

    # Independent verification: throwaway replica pulls and must match.
    src_digests = digest_tables(src, tables)
    if "kv" in src_digests:  # kv digest must exclude the skipped cache keys
        rows = [tuple(r) for r in src.execute("SELECT * FROM kv").fetchall()
                if not db.is_local_only_key(r[0])]
        acc = 0
        for r in rows:
            acc ^= int.from_bytes(hashlib.sha256(repr(r).encode()).digest()[:16], "big")
        src_digests["kv"] = (len(rows), f"{acc:032x}")
    src.close()

    tmp = Path(tempfile.mkdtemp(prefix="seed-verify-"))
    try:
        ver = libsql.connect(str(tmp / "verify.db"), sync_url=url,
                             auth_token=token, offline=True)
        ver.sync()
        ver_digests = digest_tables(ver, tables)
        ver.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if ver_digests == src_digests:
        print("VERIFIED: independent replica pulled content identical to source")
        return 0
    print("MISMATCH between source and pulled replica:")
    for t in tables:
        if src_digests.get(t) != ver_digests.get(t):
            print(f"  {t}: source={src_digests.get(t)} pulled={ver_digests.get(t)}")
    print("The synced DB should not be trusted — investigate before using it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
