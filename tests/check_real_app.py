"""
Checks that only the real, built Tauri app can answer. Manual: it opens the
app window twice, so it is not part of run_all.py.

    npm run tauri build   (or python scripts/make_release.py)
    cd src-python
    .venv/Scripts/python ../tests/check_real_app.py

A. Which Origin does the app's webview send? A throwaway server takes port
   8765 first and records it. Its CORS allowance is compared with the real
   server's. A mismatch is how the installed app once sat on "Starting
   engine..." forever: the webview is http://tauri.localhost on Windows,
   and the backend only allowed tauri://localhost.

B. Does closing the app window stop its backend? The rehearsal simulates
   the app with a stand-in process, which missed a real failure: the
   backend's output was a pipe to the app, the watchdog's last message
   failed once the app was gone, and it stopped watching instead of
   exiting. Only launching the real app catches that class of bug.

Runs against your real app-data folder, exactly like opening the app.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "src-tauri" / "target" / "release" / "workspace.exe"
LOG = Path(os.environ.get("APPDATA", "")) / "com.michael.workspace" / "sidecar.log"


def sidecar_pids() -> list[str]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name LIKE 'workspace-sidecar%'\" | "
         "ForEach-Object { $_.ProcessId }"],
        capture_output=True, text=True).stdout
    return [l.strip() for l in out.splitlines() if l.strip()]


def listening() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2)
        return True
    except Exception:
        return False


def close_app(p: subprocess.Popen) -> str:
    subprocess.run(["taskkill", "/PID", str(p.pid)], capture_output=True)  # like clicking X
    try:
        p.wait(timeout=15)
        return f"closed normally (exit code {p.returncode})"
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True)
        p.wait(timeout=10)
        return "ignored the close request; force-killed"


def kill_sidecars() -> None:
    subprocess.run(["taskkill", "/F", "/T", "/IM", "workspace-sidecar.exe"],
                   capture_output=True)


def server_allowed_origins() -> list[str]:
    sys.path.insert(0, str(REPO / "src-python"))
    import server
    for m in server.app.user_middleware:
        if "CORS" in str(m.cls):
            return list(m.kwargs["allow_origins"])
    return []


def check_origin() -> None:
    origins: list[str | None] = []

    class Recorder(BaseHTTPRequestHandler):
        def do_GET(self):
            origins.append(self.headers.get("Origin"))
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 8765), Recorder)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    app = subprocess.Popen([str(APP)])
    try:
        time.sleep(12)
    finally:
        close_app(app)
        srv.shutdown()
        srv.server_close()
        kill_sidecars()   # the app's own backend could not bind; don't leave it

    seen = sorted({o for o in origins if o})
    assert origins, "the webview made no requests — could not observe its origin"
    allowed = server_allowed_origins()
    missing = [o for o in seen if o not in allowed]
    assert not missing, f"webview origin(s) {missing} not in server CORS {allowed}"
    print(f"A. webview sent Origin {seen} on {len(origins)} requests; all allowed by the server")


def check_close() -> None:
    for _ in range(10):
        if not listening() and not sidecar_pids():
            break
        time.sleep(1)
    else:
        raise SystemExit(f"leftover backend before check B: {sidecar_pids()}")

    app = subprocess.Popen([str(APP)])
    for _ in range(60):
        if listening():
            break
        time.sleep(1)
    else:
        close_app(app)
        raise SystemExit("B. the app's backend never came up")
    time.sleep(4)  # let the orphan guard start and log its target
    how = close_app(app)

    t0 = time.time()
    while time.time() - t0 < 20 and (sidecar_pids() or listening()):
        time.sleep(1)
    left = sidecar_pids()
    if left:
        tail = LOG.read_text(errors="replace")[-1500:] if LOG.exists() else "(no log)"
        kill_sidecars()
        raise SystemExit(f"B. FAIL: backend outlived the app ({how}): {left}\n"
                         f"--- sidecar.log tail:\n{tail}")
    guard = [l for l in LOG.read_text(errors="replace").splitlines()
             if "orphan guard" in l] if LOG.exists() else []
    print(f"B. app {how}; backend exited within {time.time() - t0:.0f}s")
    for line in guard:
        print(f"   {line}")


def main() -> int:
    if not APP.exists():
        raise SystemExit(f"built app not found: {APP}")
    if listening() or sidecar_pids():
        raise SystemExit("close Workspace first — port 8765 or a backend is in use")
    check_origin()
    check_close()
    print("\nREAL-APP CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
