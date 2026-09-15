"""
Broken-replica repair: a replica whose sync log was destroyed by an outside
SQLite connection must be detected and rebuilt, with no edit lost.

The failure this guards against is silent: once any plain SQLite connection
opens and closes a libSQL synced replica, SQLite checkpoints and deletes its
WAL, and every later sync() does nothing in either direction while still
reporting success. It went unnoticed until a long-lived replica was found
reverting deletions, because every other test uses a brand-new replica.

Steps, each in its own process as its own "machine":
    a-setup    A creates a disposable trade and pushes it
    a-break    the replica is opened and closed with stdlib sqlite3, exactly
               as the old backup script did; the log check must flag it
    a-repair   A edits the trade through the broken replica, then syncs via
               the real SyncManager: it must repair, and the edit must land
    b-verify   a fresh machine B sees the edit (it reached the cloud)
    b-edit     B makes a second edit and pushes
    a-receive  A pulls B's edit (the repaired replica receives again)
    cleanup    removes the trade and its tombstone; C verifies

Uses one disposable trade (id test-repair-1). Needs network + credentials.
"""

from __future__ import annotations

import copy
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _machines import dispatch, engine, run_step  # noqa: E402

WORKDIR = Path(tempfile.gettempdir()) / "workspace-repair-test"
TEST = {"id": "test-repair-1", "ticker": "TSTX", "entryDate": "2026-09-15",
        "entryPrice": 3.0, "notes": "v1"}


def _notes() -> dict:
    _, ledger_db, _ = engine()
    return {t["id"]: t.get("notes") for t in ledger_db.load_trades()}


def _set_notes(value: str) -> None:
    _, ledger_db, _ = engine()
    trades = ledger_db.load_trades()
    for t in trades:
        if t["id"] == TEST["id"]:
            t["notes"] = value
    ledger_db.save_trades(trades)


def a_setup():
    db, ledger_db, _ = engine()
    trades = ledger_db.load_trades() or []
    assert not any(t["id"] == TEST["id"] for t in trades), "leftover test row"
    trades.append(copy.deepcopy(TEST))
    ledger_db.save_trades(trades)
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, err
    assert db.replica_log_intact() is True, "a freshly synced replica should pass"
    print("a-setup: test trade pushed; replica log intact")


def a_break():
    path = os.environ["WORKSPACE_SYNCED_DB_PATH"]
    src = sqlite3.connect(path)
    dst = sqlite3.connect(Path(path).with_name("throwaway-backup.db"))
    src.backup(dst)
    dst.close()
    src.close()
    db, _, _ = engine()
    assert db.replica_log_intact() is False, "log check failed to flag a destroyed WAL"
    print("a-break: replica opened+closed with plain sqlite3; log check flags it as broken")


def a_repair():
    import threading
    db, ledger_db, _ = engine()
    _set_notes("edited on the broken replica")
    mgr = db.SyncManager(ledger_db._connect, ledger_db._lock, interval=3600,
                         swap_conn=ledger_db.swap_connection)

    # Requests keep arriving while the replica is rebuilt — at app startup
    # the UI loads trades at exactly the moment a repair runs. A handler
    # holding the connection from before the rebuild must not end up
    # querying the closed handle (which surfaced as HTTP 500s).
    reader_errors: list[str] = []
    reads = 0
    stop = threading.Event()

    def reader():
        nonlocal reads
        while not stop.is_set():
            try:
                ledger_db.load_trades()
                reads += 1
            # BaseException, not Exception: a query on a closed libSQL handle
            # raises pyo3's PanicException, which is not an Exception. Catching
            # only Exception let it kill this thread silently, and the test
            # passed against the very bug it exists to catch.
            except BaseException as exc:
                reader_errors.append(f"{type(exc).__name__}: {exc}")

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    ok, err = mgr.sync_now()
    reader_alive = t.is_alive()
    stop.set()
    t.join(timeout=30)
    assert reader_alive, "reader thread died during the repair"
    assert not reader_errors, (
        f"{len(reader_errors)} of {reads + len(reader_errors)} concurrent reads failed "
        f"during repair, e.g. {reader_errors[0]}")
    print(f"a-repair: {reads} concurrent reads during the rebuild, none failed")
    if not ok:
        import time
        for _ in range(6):
            time.sleep(3)
            ok, err = mgr.sync_now()
            if ok:
                break
    assert ok, f"repair did not complete: {err}"
    assert db.replica_log_intact() is True, "replica still broken after repair"
    assert _notes()[TEST["id"]] == "edited on the broken replica", "local edit lost in repair"
    print("a-repair: detected, rebuilt, merged; the edit made while broken survived")


def b_verify():
    assert _notes().get(TEST["id"]) == "edited on the broken replica", (
        "edit made on the broken replica never reached the cloud")
    print("b-verify: fresh machine sees the edit")


def b_edit():
    db, ledger_db, _ = engine()
    _set_notes("edited on B after repair")
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, err
    print("b-edit: second edit pushed from B")


def a_receive():
    db, ledger_db, _ = engine()
    ok, err = db.try_sync(ledger_db._connect())
    assert ok, err
    assert _notes()[TEST["id"]] == "edited on B after repair", (
        "repaired replica is not receiving remote changes")
    print("a-receive: repaired replica receives remote edits again")


def cleanup():
    db, ledger_db, _ = engine()
    conn = ledger_db._connect()
    ok, err = db.try_sync(conn)
    assert ok, err
    ledger_db.save_trades([t for t in ledger_db.load_trades() if t["id"] != TEST["id"]])
    with ledger_db._lock:
        conn.execute("DELETE FROM tombstones WHERE row_id = ?", (TEST["id"],))
        conn.commit()
    ok, err = db.try_sync(conn)
    assert ok, err
    print("cleanup: test trade and tombstone removed")


def verify_clean():
    _, ledger_db, _ = engine()
    conn = ledger_db._connect()
    assert TEST["id"] not in _notes(), "test trade leaked"
    n = conn.execute("SELECT COUNT(*) FROM tombstones WHERE row_id = ?",
                     (TEST["id"],)).fetchone()[0]
    assert n == 0, "test tombstone leaked"
    print(f"verify-clean: fresh replica has {len(ledger_db.load_trades())} trades, no leftovers")


STEPS = {"a-setup": a_setup, "a-break": a_break, "a-repair": a_repair,
         "b-verify": b_verify, "b-edit": b_edit, "a-receive": a_receive,
         "cleanup": cleanup, "verify-clean": verify_clean}


def main() -> int:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    run_step(__file__, WORKDIR, "a-setup", "A")
    run_step(__file__, WORKDIR, "a-break", "A")
    run_step(__file__, WORKDIR, "a-repair", "A")
    run_step(__file__, WORKDIR, "b-verify", "B")
    run_step(__file__, WORKDIR, "b-edit", "B")
    run_step(__file__, WORKDIR, "a-receive", "A")
    run_step(__file__, WORKDIR, "cleanup", "A")
    run_step(__file__, WORKDIR, "verify-clean", "C")
    print("\nREPLICA REPAIR TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(dispatch(STEPS, main))
