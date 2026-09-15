"""
Round-trip test: a write on replica A appears on replica B (and back).

Runs against the real Turso database using one disposable trade
(id test-rt-1) that is created, edited, and fully removed — real rows are
never written. Needs network + credentials.
"""

from __future__ import annotations

import copy
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _machines import dispatch, engine, run_step  # noqa: E402

WORKDIR = Path(tempfile.gettempdir()) / "workspace-roundtrip-test"

TEST = {"id": "test-rt-1", "ticker": "TSTR", "entryDate": "2026-09-10",
        "entryPrice": 5.0, "notes": "round-trip probe"}


def a_write():
    db, ledger_db, _ = engine()
    trades = ledger_db.load_trades() or []
    assert not any(t["id"] == TEST["id"] for t in trades), "leftover test row"
    trades.append(copy.deepcopy(TEST))
    ledger_db.save_trades(trades)
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, err
    print("A: wrote test-rt-1 and pushed")


def b_sees():
    _, ledger_db, _ = engine()
    trades = {t["id"]: t for t in ledger_db.load_trades()}
    assert TEST["id"] in trades, "A's write did not reach B"
    assert trades[TEST["id"]]["notes"] == "round-trip probe"
    print("B: sees A's write after pull")


def b_edit():
    db, ledger_db, _ = engine()
    trades = ledger_db.load_trades()
    for t in trades:
        if t["id"] == TEST["id"]:
            t["notes"] = "edited on B"
    ledger_db.save_trades(trades)
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, err
    print("B: edited test-rt-1 and pushed")


def a_sees_edit():
    db, ledger_db, _ = engine()
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, err
    trades = {t["id"]: t for t in ledger_db.load_trades()}
    assert trades[TEST["id"]]["notes"] == "edited on B", "B's edit did not reach A"
    print("A: sees B's edit after pull")


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
    assert not any(t["id"] == TEST["id"] for t in trades), "test trade leaked"
    n = conn.execute("SELECT COUNT(*) FROM tombstones WHERE row_id = ?",
                     (TEST["id"],)).fetchone()[0]
    assert n == 0, "test tombstone leaked"
    print(f"fresh replica: {len(trades)} trades, no leftovers")


STEPS = {"a-write": a_write, "b-sees": b_sees, "b-edit": b_edit,
         "a-sees-edit": a_sees_edit, "a-cleanup": a_cleanup,
         "verify-clean": verify_clean}


def main() -> int:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    run_step(__file__, WORKDIR, "a-write", "A")
    run_step(__file__, WORKDIR, "b-sees", "B")
    run_step(__file__, WORKDIR, "b-edit", "B")
    run_step(__file__, WORKDIR, "a-sees-edit", "A")
    run_step(__file__, WORKDIR, "a-cleanup", "A")
    run_step(__file__, WORKDIR, "verify-clean", "C")
    print("\nROUND-TRIP TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(dispatch(STEPS, main))
