"""
End-to-end conflict test: two simulated machines diverge, the loser's sync
conflicts, reconciliation merges per-row LWW, both converge.

Runs against the REAL Turso database, but only ever touches two test trades
(ids test-p5-a / test-p5-b) that it creates and fully removes — the real
rows are read, never written. Each "machine" is a subprocess with its own
WORKSPACE_SYNCED_DB_PATH, exercising the actual engine code path.

Usage (from src-python, venv python — needs network + credentials):

    .venv/Scripts/python ../tests/test_conflict_reconcile.py

Steps (also invokable individually with --step for debugging):
    a-setup     A creates the two test trades and pushes
    b-pull      B pulls and sees them
    a-edit      A edits test-p5-a and pushes
    b-diverge   B (offline: unreachable sync host) edits test-p5-b
    b-reconcile B reconnects; sync conflicts; reconcile merges; verify both edits
    a-verify    A pulls; verify both edits
    a-cleanup   A deletes the test trades and their tombstones, pushes
    verify-clean fresh replica: 40 real trades, no test leftovers
"""

from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC_PYTHON = Path(__file__).resolve().parent.parent / "src-python"
sys.path.insert(0, str(SRC_PYTHON))

WORKDIR = Path(tempfile.gettempdir()) / "workspace-conflict-test"
BAD_URL = "libsql://offline-test-nonexistent-host.turso.io"

TEST_A = {"id": "test-p5-a", "ticker": "TSTA", "entryDate": "2026-09-09",
          "entryPrice": 1.0, "notes": "conflict-test row A"}
TEST_B = {"id": "test-p5-b", "ticker": "TSTB", "entryDate": "2026-09-09",
          "entryPrice": 2.0, "notes": "conflict-test row B"}


def engine():
    from engine import db, ledger_db, reconcile
    return db, ledger_db, reconcile


def step_a_setup():
    db, ledger_db, _ = engine()
    trades = ledger_db.load_trades() or []
    assert not any(t["id"].startswith("test-p5-") for t in trades), "leftover test rows"
    base = len(trades)
    trades += [copy.deepcopy(TEST_A), copy.deepcopy(TEST_B)]
    ledger_db.save_trades(trades)
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, err
    print(f"a-setup: {base} real trades, test rows added and pushed")


def step_b_pull():
    _, ledger_db, _ = engine()
    trades = ledger_db.load_trades()
    ids = {t["id"] for t in trades}
    assert "test-p5-a" in ids and "test-p5-b" in ids, ids
    print(f"b-pull: sees {len(trades)} trades incl. test rows")


def _edit(trade_id: str, notes: str):
    db, ledger_db, _ = engine()
    trades = ledger_db.load_trades()
    for t in trades:
        if t["id"] == trade_id:
            t["notes"] = notes
    ledger_db.save_trades(trades)
    return db, ledger_db


def step_a_edit():
    db, ledger_db = _edit("test-p5-a", "A-edit")
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, err
    print("a-edit: test-p5-a = 'A-edit', pushed")


def step_b_diverge():
    # env carries the unreachable sync host — the connect-time pull fails
    # (caught) and the write lands only in the local replica.
    db, ledger_db = _edit("test-p5-b", "B-edit")
    ok, err = db.try_sync(ledger_db._connect())
    assert not ok, "sync against unreachable host should fail"
    print(f"b-diverge: offline edit done (sync failed as expected)")


def step_b_reconcile():
    import time as _time
    db, ledger_db, reconcile = engine()
    conn = ledger_db._connect()
    # The server alternates between the real conflict response and a
    # transient 503 while the conflicted session lingers; the app's sync
    # manager naturally retries (debounce + interval), so retry here too
    # until the conflict form appears.
    err = None
    for attempt in range(8):
        ok, err = db.try_sync(conn)
        assert not ok, "sync of a diverged replica must not succeed"
        if reconcile.is_conflict_error(err):
            break
        _time.sleep(2)
    assert reconcile.is_conflict_error(err), f"never saw conflict, last: {err}"
    print(f"b-reconcile: got the conflict ({err.strip()[:60]}...)")
    ok, err = reconcile.run(conn, ledger_db._lock, ledger_db.swap_connection)
    if not ok:
        # Merge succeeded but the push was deferred (transient 503 while the
        # conflicted server session clears). Retry the push like the sync
        # manager's next cycles would.
        for attempt in range(8):
            _time.sleep(3)
            ok, err = db.try_sync(ledger_db._connect())
            if ok:
                break
    assert ok, f"reconcile push never succeeded: {err}"
    trades = {t["id"]: t for t in ledger_db.load_trades()}
    assert trades["test-p5-a"]["notes"] == "A-edit", trades["test-p5-a"]["notes"]
    assert trades["test-p5-b"]["notes"] == "B-edit", trades["test-p5-b"]["notes"]
    print("b-reconcile: merged — both A-edit and B-edit present, pushed")


def step_a_verify():
    _, ledger_db, _ = engine()
    trades = {t["id"]: t for t in ledger_db.load_trades()}
    assert trades["test-p5-a"]["notes"] == "A-edit"
    assert trades["test-p5-b"]["notes"] == "B-edit"
    print("a-verify: A sees the merged state")


def step_same_b_diverge():
    # Same-row scenario, phase 1: B edits test-p5-b OFFLINE, first in time.
    db, ledger_db = _edit("test-p5-b", "B-old-loser")
    ok, _ = db.try_sync(ledger_db._connect())
    assert not ok
    print("same-row: B's earlier offline edit stored locally")


def step_same_a_edit():
    # Phase 2: A edits the SAME row later in time and pushes. Per the
    # policy the newer write must win everywhere — including over B's
    # stranded local edit, even though B reconciles (pushes) last.
    import time as _time
    _time.sleep(1.5)  # strictly later updated_at than B's edit
    db, ledger_db = _edit("test-p5-b", "A-new-winner")
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, err
    print("same-row: A's later edit pushed")


def step_same_b_reconcile():
    import time as _time
    db, ledger_db, reconcile = engine()
    conn = ledger_db._connect()
    err = None
    for attempt in range(8):
        ok, err = db.try_sync(conn)
        assert not ok, "diverged replica must conflict"
        if reconcile.is_conflict_error(err):
            break
        _time.sleep(2)
    assert reconcile.is_conflict_error(err), f"never saw conflict: {err}"
    ok, err = reconcile.run(conn, ledger_db._lock, ledger_db.swap_connection)
    if not ok:
        for attempt in range(8):
            _time.sleep(3)
            ok, err = db.try_sync(ledger_db._connect())
            if ok:
                break
    assert ok, f"reconcile push never succeeded: {err}"
    trades = {t["id"]: t for t in ledger_db.load_trades()}
    assert trades["test-p5-b"]["notes"] == "A-new-winner", (
        f"older local edit survived over newer cloud edit: "
        f"{trades['test-p5-b']['notes']}")
    assert trades["test-p5-a"]["notes"] == "A-edit"
    print("same-row: reconciled — the NEWER write won, B's older edit "
          "correctly discarded (timestamps decide, not push order)")


def step_same_a_verify():
    _, ledger_db, _ = engine()
    trades = {t["id"]: t for t in ledger_db.load_trades()}
    assert trades["test-p5-b"]["notes"] == "A-new-winner"
    print("same-row: A confirms the converged state")


def step_a_cleanup():
    db, ledger_db, _ = engine()
    trades = [t for t in ledger_db.load_trades()
              if not t["id"].startswith("test-p5-")]
    ledger_db.save_trades(trades)
    conn = ledger_db._connect()
    with ledger_db._lock:
        conn.execute("DELETE FROM tombstones WHERE row_id LIKE 'test-p5-%'")
        conn.commit()
    ok, err = db.try_sync(conn)
    assert ok, err
    print(f"a-cleanup: test rows and their tombstones removed, {len(trades)} trades remain")


def step_verify_clean():
    _, ledger_db, _ = engine()
    conn = ledger_db._connect()
    trades = ledger_db.load_trades()
    assert not any(t["id"].startswith("test-p5-") for t in trades), "test trades leaked"
    n = conn.execute("SELECT COUNT(*) FROM tombstones WHERE row_id LIKE 'test-p5-%'").fetchone()[0]
    assert n == 0, "test tombstones leaked"
    print(f"verify-clean: fresh replica has {len(trades)} trades, no test leftovers")


STEPS = {
    "a-setup": step_a_setup, "b-pull": step_b_pull, "a-edit": step_a_edit,
    "b-diverge": step_b_diverge, "b-reconcile": step_b_reconcile,
    "a-verify": step_a_verify, "a-cleanup": step_a_cleanup,
    "same-b-diverge": step_same_b_diverge, "same-a-edit": step_same_a_edit,
    "same-b-reconcile": step_same_b_reconcile,
    "same-a-verify": step_same_a_verify,
    "verify-clean": step_verify_clean,
}


def run_step(step: str, machine: str, offline: bool = False) -> None:
    env = dict(os.environ)
    env["WORKSPACE_SYNCED_DB_PATH"] = str(WORKDIR / machine / "synced.db")
    if offline:
        env["TURSO_DATABASE_URL"] = BAD_URL
        env["TURSO_AUTH_TOKEN"] = "dummy"
    r = subprocess.run([sys.executable, __file__, "--step", step],
                       env=env, cwd=SRC_PYTHON)
    if r.returncode != 0:
        print(f"STEP FAILED: {step}")
        sys.exit(1)


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--step":
        STEPS[sys.argv[2]]()
        return 0

    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    for m in ("A", "B", "C"):
        (WORKDIR / m).mkdir(parents=True)

    # Scenario 1: different rows edited on each machine — both edits survive.
    run_step("a-setup", "A")
    run_step("b-pull", "B")
    run_step("a-edit", "A")
    run_step("b-diverge", "B", offline=True)
    run_step("b-reconcile", "B")
    run_step("a-verify", "A")
    # Scenario 2: the SAME row edited on both — the newer timestamp wins,
    # even though the machine holding the older edit pushes last.
    run_step("same-b-diverge", "B", offline=True)
    run_step("same-a-edit", "A")
    run_step("same-b-reconcile", "B")
    run_step("same-a-verify", "A")
    run_step("a-cleanup", "A")
    run_step("verify-clean", "C")
    print("\nCONFLICT/RECONCILE TEST: ALL STEPS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
