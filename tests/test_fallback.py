"""
Fallback test: with no Turso credentials the app runs on plain local
SQLite, fully functional, zero network. Also carries the write-discipline
suite (diff save, tombstones, resurrection guard) since those semantics are
mode-independent and this is the mode where they can run hermetically.

Two parts:
  1. engine-level checks in this process (scratch copies, credentials
     suppressed via empty env vars)
  2. a real sidecar subprocess started with no credentials on a spare
     port, exercised over HTTP
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC_PYTHON = REPO / "src-python"
LIVE = SRC_PYTHON / "engine" / "workspace.db"
PORT = 8766


def http(path: str, body: dict | None = None):
    url = f"http://127.0.0.1:{PORT}{path}"
    if body is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def engine_checks(work: Path) -> None:
    os.environ["TURSO_DATABASE_URL"] = ""
    os.environ["TURSO_AUTH_TOKEN"] = ""
    os.environ["WORKSPACE_DB_PATH"] = str(work / "state.db")
    os.environ["WORKSPACE_CACHE_DB_PATH"] = str(work / "cache.db")
    shutil.copy(LIVE, work / "state.db")

    sys.path.insert(0, str(SRC_PYTHON))
    from engine import db, ledger_db, lists_db

    assert db.mode() == "local", db.mode()
    conn = ledger_db._connect()
    expected = sqlite3.connect(
        f"file:{(work / 'state.db').as_posix()}?mode=ro", uri=True
    ).execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    trades = ledger_db.load_trades()
    assert len(trades) == expected and expected > 0, (len(trades), expected)
    print(f"local mode: {len(trades)} trades load with no credentials, no network")

    # kv routing: cache-prefixed keys never land in the state DB
    ledger_db.set_kv("rotation:cache_at", "999")
    assert ledger_db.get_kv("rotation:cache_at") == "999"
    keys = [r["key"] for r in conn.execute("SELECT key FROM kv").fetchall()]
    assert not any(db.is_local_only_key(k) for k in keys), keys
    print("kv routing: cache keys stay out of the state DB")

    def stamps():
        return {r["id"]: r["updated_at"]
                for r in conn.execute("SELECT id, updated_at FROM trades").fetchall()}

    # -- write discipline (feeds the conflict policy) --
    s0 = stamps()
    ledger_db.save_trades(copy.deepcopy(trades))
    assert stamps() == s0, "identical save touched rows"

    trades[0]["notes"] = "fallback-suite edit"
    ledger_db.save_trades(copy.deepcopy(trades))
    s1 = stamps()
    assert [t for t in s1 if s1[t] != s0[t]] == [trades[0]["id"]]

    victim = trades.pop(1)
    ledger_db.save_trades(copy.deepcopy(trades))
    tomb = conn.execute(
        "SELECT content_hash FROM tombstones WHERE table_name='trades' AND row_id=?",
        (victim["id"],)).fetchone()
    assert tomb and tomb["content_hash"]

    stale = copy.deepcopy(trades)
    stale.insert(1, copy.deepcopy(victim))
    ledger_db.save_trades(stale)
    assert conn.execute("SELECT 1 FROM trades WHERE id=?", (victim["id"],)).fetchone() is None

    readd = copy.deepcopy(victim)
    readd["notes"] = "deliberate re-add"
    trades.insert(1, readd)
    ledger_db.save_trades(copy.deepcopy(trades))
    assert conn.execute("SELECT 1 FROM trades WHERE id=?", (victim["id"],)).fetchone() is not None
    assert conn.execute(
        "SELECT 1 FROM tombstones WHERE table_name='trades' AND row_id=?",
        (victim["id"],)).fetchone() is None

    before = conn.execute(
        "SELECT updated_at FROM kv WHERE key='ledger:initialized'").fetchone()["updated_at"]
    ledger_db.set_kv("ledger:initialized", "true")
    assert conn.execute(
        "SELECT updated_at FROM kv WHERE key='ledger:initialized'").fetchone()["updated_at"] == before

    lst = lists_db.add_list("fallback-temp")
    item = lists_db.add_item(lst["id"], "x")
    lists_db.delete_list(lst["id"])
    assert conn.execute(
        "SELECT 1 FROM tombstones WHERE table_name='lists' AND row_id=?",
        (lst["id"],)).fetchone()
    assert conn.execute(
        "SELECT 1 FROM tombstones WHERE table_name='list_items' AND row_id=?",
        (item["id"],)).fetchone()
    print("write discipline: no-op skip, single-row bump, tombstone+hash, "
          "resurrection block, deliberate re-add, kv skip, list tombstones")


def sidecar_checks(work: Path) -> None:
    env = dict(os.environ)
    env["TURSO_DATABASE_URL"] = ""
    env["TURSO_AUTH_TOKEN"] = ""
    env["WORKSPACE_DB_PATH"] = str(work / "sidecar-state.db")
    env["WORKSPACE_CACHE_DB_PATH"] = str(work / "sidecar-cache.db")
    shutil.copy(LIVE, work / "sidecar-state.db")

    python = SRC_PYTHON / ".venv" / "Scripts" / "python.exe"
    proc = subprocess.Popen(
        [str(python), "-m", "uvicorn", "server:app", "--port", str(PORT)],
        cwd=SRC_PYTHON, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                if http("/health")["ok"]:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise AssertionError("sidecar never came up")

        st = http("/sync/status")
        assert st["mode"] == "local", st
        trades = http("/ledger/trades")["trades"]
        assert trades and len(trades) > 0
        lists_resp = http("/lists")
        assert "lists" in lists_resp
        http("/ledger/kv/set", {"key": "fallback:probe", "value": "1"})
        assert http("/ledger/kv/get", {"key": "fallback:probe"})["value"] == "1"
        sync = http("/sync/now", {})
        assert sync["ok"] is True  # local mode: nothing to sync is not a failure
        print(f"sidecar (no credentials): health, {len(trades)} trades over HTTP, "
              "lists, kv round trip, /sync reports local mode")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="fallback-test-"))
    try:
        engine_checks(work)
        sidecar_checks(work)
        print("\nFALLBACK TESTS PASSED")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
