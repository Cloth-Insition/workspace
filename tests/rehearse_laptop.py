"""
Definition-of-done rehearsal, driven through the PACKAGED sidecar binary.

Simulates a fresh laptop by pointing the frozen exe at an empty APPDATA:

    pull history -> work offline -> reconnect -> reconcile -> desktop agrees

This is the one test that exercises the shipped artifact rather than the
source tree, so it catches packaging faults the rest of the suite cannot —
it is how the orphaned-sidecar bug (a killed bootloader leaving its child
holding port 8765) was found.

Not part of run_all.py: it needs the built sidecar and takes a minute.
Build first, then run from src-python with the venv python:

    .venv/Scripts/python ../scripts/build_sidecar.py
    .venv/Scripts/python ../tests/rehearse_laptop.py

Touches real data only by creating one disposable list, which it removes
and verifies gone. Trades are read, never written.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "src-tauri" / "binaries" / "workspace-sidecar-x86_64-pc-windows-msvc.exe"
ENV_SRC = REPO / "src-python" / ".env"
SCRATCH = Path(tempfile.gettempdir()) / "workspace-laptop-sim"
BAD_URL = "libsql://offline-test-nonexistent-host.turso.io"
LIST_NAME = "sync-rehearsal"
PORT = 8765


def http(path: str, body=None, timeout=20):
    url = f"http://127.0.0.1:{PORT}{path}"
    req = (urllib.request.Request(url) if body is None else
           urllib.request.Request(url, data=json.dumps(body).encode(),
                                  headers={"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def port_busy() -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def wait_port_free(timeout: int = 40) -> None:
    """A sidecar that outlives its stop() would answer the next health check
    and silently invalidate the whole rehearsal — so never start one until
    the port is genuinely free."""
    for _ in range(timeout):
        if not port_busy():
            return
        time.sleep(1)
    raise SystemExit(f"port {PORT} never freed — stale sidecar still running")


def start(offline: bool, app_pid: int | None = None):
    wait_port_free()
    env = dict(os.environ)
    env["APPDATA"] = str(SCRATCH)          # the whole point: a fresh machine
    env["TURSO_SYNC_INTERVAL"] = "20"
    if app_pid is not None:
        env["WORKSPACE_APP_PID"] = str(app_pid)
    if offline:
        env["TURSO_DATABASE_URL"] = BAD_URL
        env["TURSO_AUTH_TOKEN"] = "dummy"
    log = open(SCRATCH / "sidecar.log", "ab")
    p = subprocess.Popen([str(EXE)], env=env, stdout=log, stderr=log)
    for _ in range(60):
        try:
            http("/health", timeout=3)
            return p
        except Exception:
            time.sleep(1)
    p.kill()
    tail = (SCRATCH / "sidecar.log").read_text(errors="replace")[-800:]
    raise SystemExit("packaged sidecar never came up. log:\n" + tail)


def stop(p):
    # /T kills the whole tree: a PyInstaller one-file build is a bootloader
    # plus the child that actually serves, and terminating only the
    # bootloader leaves the child holding the port.
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                   capture_output=True)
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait(timeout=10)
    wait_port_free()


def main() -> int:
    if not EXE.exists():
        raise SystemExit(f"packaged sidecar missing: {EXE}\n"
                         "Build it: .venv/Scripts/python ../scripts/build_sidecar.py")
    if not ENV_SRC.exists():
        raise SystemExit(f"no credentials at {ENV_SRC} — this rehearsal needs sync")
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    d = SCRATCH / "com.michael.workspace"
    d.mkdir(parents=True)
    shutil.copy(ENV_SRC, d / ".env")
    print(f"fresh 'laptop' app-data: {d}\n")

    # 0. The sidecar must exit on its own when the app does. Tauri never
    # stops it, so a stand-in "app" process is started, its PID handed over
    # exactly as main.rs does, and then killed — without touching the
    # sidecar. If the port is not released, the next real launch would fail.
    stand_in = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    p = start(offline=False, app_pid=stand_in.pid)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/health",
                                     headers={"Origin": "http://tauri.localhost"})
        with urllib.request.urlopen(req, timeout=10) as r:
            acao = r.headers.get("access-control-allow-origin")
        assert acao == "http://tauri.localhost", (
            f"packaged sidecar blocks the Windows app origin (got {acao!r}) — "
            "the installed app would sit on 'Starting engine...'")
        print("0a. packaged sidecar allows the Windows webview origin (CORS)")

        stand_in.kill()
        stand_in.wait(timeout=10)
        for waited in range(20):
            if not port_busy():
                break
            time.sleep(1)
        else:
            raise SystemExit("sidecar outlived the app — port 8765 still held")
        print(f"0b. killed the stand-in app; sidecar exited by itself within {waited + 1}s")
    finally:
        if stand_in.poll() is None:
            stand_in.kill()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        wait_port_free()

    # 1. First launch: pull existing history.
    p = start(offline=False)
    try:
        trades = http("/ledger/trades")["trades"]
        st = http("/sync/status")
        assert st["mode"] == "synced", st
        assert trades, "fresh install pulled no trades"
        print(f"1. fresh install pulled {len(trades)} trades, mode={st['mode']}")

        lst = http("/lists/add", {"name": LIST_NAME})
        list_id = lst["id"]
        http("/lists/item/add", {"list_id": list_id, "text": "created online"})
        time.sleep(6)   # let the debounced sync push it
        st = http("/sync/status")
        assert st["last_error"] is None, st
        print("2. created a list online and pushed")
    finally:
        stop(p)

    # 2. On the train: same replica, network gone.
    p = start(offline=True)
    try:
        st = http("/sync/status")
        assert st["mode"] == "synced"
        lists = {l["id"]: l for l in http("/lists")["lists"]}
        assert list_id in lists, "pulled data missing after restart"
        http("/lists/item/add", {"list_id": list_id, "text": "written on the train"})
        items = [i["text"] for i in
                 {l["id"]: l for l in http("/lists")["lists"]}[list_id]["items"]]
        assert "written on the train" in items, items
        time.sleep(6)
        st = http("/sync/status")
        assert st["last_error"] is not None, "expected a sync failure while offline"
        print(f"3. offline: write succeeded locally, sync failing as expected "
              f"({st['pending_changes']} pending)")
    finally:
        stop(p)

    # 3. Reconnected.
    p = start(offline=False)
    try:
        r = http("/sync/now", {})
        assert r["ok"], r
        print("4. reconnected and reconciled")
    finally:
        stop(p)

    # 4. The desktop's view (independent replica, dev paths).
    sys.path.insert(0, str(REPO / "src-python"))
    from engine import db, ledger_db, lists_db   # noqa: E402
    conn = ledger_db._connect()
    ok, err = db.try_sync(conn)
    assert ok, err
    rehearsal = [l for l in lists_db.get_all()["lists"] if l["name"] == LIST_NAME]
    assert rehearsal, "desktop never saw the rehearsal list"
    texts = [i["text"] for l in rehearsal for i in l["items"]]
    assert "written on the train" in texts, texts
    print(f"5. desktop sees the train write: {texts}")

    # 5. Clean up. Every list of this name, not just one: an aborted run
    # leaves its own behind, and keying by name would hide the duplicates
    # (which is exactly how two of them once survived a "passing" run).
    for l in rehearsal:
        lists_db.delete_list(l["id"])
        with ledger_db._lock:
            conn.execute("DELETE FROM tombstones WHERE row_id = ?", (l["id"],))
            for item in l["items"]:
                conn.execute("DELETE FROM tombstones WHERE row_id = ?", (item["id"],))
            conn.commit()
    ok, err = db.try_sync(conn)
    assert ok, err
    remaining = [l["name"] for l in lists_db.get_all()["lists"]]
    assert LIST_NAME not in remaining, f"cleanup incomplete: {remaining}"
    print(f"6. cleaned up; lists now: {remaining}")

    shutil.rmtree(SCRATCH, ignore_errors=True)
    print("\nDEFINITION-OF-DONE REHEARSAL PASSED (through the packaged binary)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
