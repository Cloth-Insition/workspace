"""
Remove leftover suite artifacts from the synced database: any trade whose id
starts with 'test-' plus its tombstones, pushed to the cloud and verified
gone from an independent fresh replica.

Needed when a test run dies between creating its disposable rows and its
cleanup step (crash, kill, broken pipe). The suite's own leftover guards
refuse to run until this has been done — deliberately, so junk is removed
consciously rather than absorbed.

Never touches real rows: the filter is the id prefix, nothing else.

    cd src-python && .venv/Scripts/python ../tests/clean_test_rows.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _machines import engine  # noqa: E402


def main() -> int:
    db, ledger_db, _ = engine()
    conn = ledger_db._connect()
    ok, err = db.try_sync(conn)  # pull latest first
    if not ok:
        print(f"warning: pre-clean pull failed ({err}); cleaning local state anyway")

    trades = ledger_db.load_trades() or []
    junk = [t["id"] for t in trades if t["id"].startswith("test-")]
    if junk:
        ledger_db.save_trades([t for t in trades if not t["id"].startswith("test-")])
        print(f"removed {len(junk)} test trade(s): {junk}")
    else:
        print("no test trades present")

    with ledger_db._lock:
        n = conn.execute(
            "SELECT COUNT(*) FROM tombstones WHERE row_id LIKE 'test-%'").fetchone()[0]
        if n:
            conn.execute("DELETE FROM tombstones WHERE row_id LIKE 'test-%'")
            conn.commit()
            print(f"removed {n} test tombstone(s)")
    ok, err = db.try_sync(conn)
    if not ok:
        print(f"push failed: {err}")
        return 1

    # Independent verification from a throwaway replica.
    import os
    import libsql
    d = Path(tempfile.mkdtemp(prefix="clean-verify-"))
    try:
        v = libsql.connect(str(d / "v.db"),
                           sync_url=os.environ["TURSO_DATABASE_URL"],
                           auth_token=os.environ["TURSO_AUTH_TOKEN"], offline=True)
        v.sync()
        left = v.execute(
            "SELECT COUNT(*) FROM trades WHERE id LIKE 'test-%'").fetchone()[0]
        tomb = v.execute(
            "SELECT COUNT(*) FROM tombstones WHERE row_id LIKE 'test-%'").fetchone()[0]
        total = v.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        v.close()
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if left or tomb:
        print(f"VERIFY FAILED: {left} test trades / {tomb} test tombstones remain in cloud")
        return 1
    print(f"cloud verified clean: {total} trades, no test artifacts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
