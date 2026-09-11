"""
Offline test: write with the network down, reconnect, verify the write
reconciles to the cloud — the non-conflict offline path (nobody else wrote
meanwhile), which is the everyday train scenario.

"Network down" is simulated with an unreachable sync host, which fails at
the same point a dead network does. Uses one disposable trade
(id test-off-1); real rows are never written.
"""

from __future__ import annotations

import copy
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _machines import dispatch, engine, run_step  # noqa: E402

WORKDIR = Path(tempfile.gettempdir()) / "workspace-offline-test"

TEST = {"id": "test-off-1", "ticker": "TSTO", "entryDate": "2026-09-10",
        "entryPrice": 7.0, "notes": "written offline"}


def a_prime():
    """Establish A's replica while online."""
    _, ledger_db, _ = engine()
    trades = ledger_db.load_trades()
    assert not any(t["id"] == TEST["id"] for t in trades), "leftover test row"
    print(f"A: primed online with {len(trades)} trades")


def a_offline_write():
    """Sync host unreachable: the write must succeed locally, sync must
    fail catchably, and the app must keep serving the written data."""
    db, ledger_db, _ = engine()
    trades = ledger_db.load_trades()
    trades.append(copy.deepcopy(TEST))
    ledger_db.save_trades(trades)
    again = {t["id"]: t for t in ledger_db.load_trades()}
    assert TEST["id"] in again, "offline write not readable back"
    ok, err = db.try_sync(ledger_db._connect())
    assert not ok and err, "sync should fail with the network down"
    print("A: offline write stored locally; sync failed non-fatally")


def a_reconnect():
    """Back online: the connect-time sync pushes the queued write."""
    db, ledger_db, _ = engine()
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, f"reconnect sync failed: {err}"
    print("A: reconnected and pushed")


def b_verify():
    _, ledger_db, _ = engine()
    trades = {t["id"]: t for t in ledger_db.load_trades()}
    assert TEST["id"] in trades, "offline write never reached the cloud"
    assert trades[TEST["id"]]["notes"] == "written offline"
    print("B: fresh replica sees the offline write")


def a_cleanup():
    db, ledger_db, _ = engine()
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, err
    trades = [t for t in ledger_db.load_trades() if t["id"] != TEST["id"]]
    ledger_db.save_trades(trades)
    conn = ledger_db._connect()
    with ledger_db._lock:
        conn.execute("DELETE FROM tombstones WHERE row_id = ?", (TEST["id"],))
        conn.commit()
    ok, err = db.try_sync(conn)
    assert ok, err
    print(f"A: cleaned up ({len(trades)} trades remain)")


def verify_clean():
    _, ledger_db, _ = engine()
    conn = ledger_db._connect()
    trades = ledger_db.load_trades()
    assert not any(t["id"] == TEST["id"] for t in trades)
    n = conn.execute("SELECT COUNT(*) FROM tombstones WHERE row_id = ?",
                     (TEST["id"],)).fetchone()[0]
    assert n == 0
    print(f"fresh replica: {len(trades)} trades, no leftovers")


STEPS = {"a-prime": a_prime, "a-offline-write": a_offline_write,
         "a-reconnect": a_reconnect, "b-verify": b_verify,
         "a-cleanup": a_cleanup, "verify-clean": verify_clean}


def main() -> int:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    run_step(__file__, WORKDIR, "a-prime", "A")
    run_step(__file__, WORKDIR, "a-offline-write", "A", offline=True)
    run_step(__file__, WORKDIR, "a-reconnect", "A")
    run_step(__file__, WORKDIR, "b-verify", "B")
    run_step(__file__, WORKDIR, "a-cleanup", "A")
    run_step(__file__, WORKDIR, "verify-clean", "C")
    print("\nOFFLINE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(dispatch(STEPS, main))
