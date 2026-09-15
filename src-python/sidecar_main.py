"""
Entry point for the PyInstaller-frozen sidecar binary.

The dev path stays `python -m uvicorn server:app --port 8765 --reload`;
this module exists only so the frozen exe has a static import root that
PyInstaller can walk (server -> engine.*). Built by
scripts/build_sidecar.py into src-tauri/binaries/, which Tauri bundles as
an external binary and spawns in release builds (see src-tauri/src/main.rs).

Logging: the release app has no console, so anything written to stdout or
stderr — tracebacks, sync errors, libSQL's Rust panic messages — went into
a pipe nobody reads. Frozen builds instead write to sidecar.log in the app
data dir (%APPDATA%\\com.michael.workspace), keeping the previous launch's
log as sidecar.previous.log.

Orphan guard: Tauri does not stop spawned processes when the app exits,
and a PyInstaller one-file build is itself two processes — a bootloader
and the child that actually runs this code. An orphaned child keeps port
8765, so the NEXT launch's sidecar cannot bind and the app never gets a
working backend. So this process watches the app and exits when it goes.

What to watch: the app passes its own PID in WORKSPACE_APP_PID. Watching
the immediate parent instead is not enough — that is the bootloader, which
lives exactly as long as this child does, so it never disappears first.
The parent PID is only a fallback for a sidecar launched some other way.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

PARENT_POLL_SECONDS = 3


def _log(msg: str) -> None:
    try:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [sidecar] {msg}",
              file=sys.stderr, flush=True)
    except BaseException:
        pass  # logging must never be the reason anything else fails


def _log_to_file() -> Path | None:
    """Send this process's stdout and stderr — including native writes to
    file descriptors 1 and 2, where Rust panics go — to a log file."""
    from engine.db import app_data_dir

    d = app_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    log = d / "sidecar.log"
    try:
        if log.exists():
            os.replace(log, d / "sidecar.previous.log")
    except OSError:
        pass  # still held by a sidecar that is shutting down: append instead
    f = open(log, "a", buffering=1, encoding="utf-8", errors="replace")
    os.dup2(f.fileno(), 1)
    os.dup2(f.fileno(), 2)
    sys.stdout = sys.stderr = f
    return log


def _process_alive(pid: int) -> bool:
    """Windows: is this PID still a running process?"""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _watched_pid() -> tuple[int | None, str]:
    raw = os.environ.get("WORKSPACE_APP_PID", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw), "WORKSPACE_APP_PID"
    try:
        ppid = os.getppid()
    except Exception:
        return None, "none"
    return (ppid, "parent process") if ppid > 0 else (None, "none")


def _exit_with_app() -> None:
    """Exit when the app that launched us does.

    os._exit rather than a graceful shutdown: the app is already gone,
    nothing is waiting on a clean response, and the point is to release the
    port immediately. Sync state is durable — every write is committed
    before its response returns, and unsynced local changes reconcile on
    the next launch.
    """
    pid, source = _watched_pid()
    if pid is None:
        _log("orphan guard: no process to watch — disabled")
        return
    _log(f"orphan guard: watching pid {pid} (from {source}); own pid {os.getpid()}")
    reported = False
    while True:
        time.sleep(PARENT_POLL_SECONDS)
        try:
            alive = _process_alive(pid)
        except BaseException as exc:
            if not reported:  # keep watching; a transient failure must not end the guard
                _log(f"orphan guard: liveness check failed ({exc!r}); still watching")
                reported = True
            continue
        if not alive:
            _log(f"orphan guard: pid {pid} is gone — exiting")
            os._exit(0)


if __name__ == "__main__":
    frozen = getattr(sys, "frozen", False)
    if frozen:
        try:
            log_path = _log_to_file()
            _log(f"started; logging to {log_path}")
        except BaseException as exc:
            _log(f"could not open log file ({exc!r}); output stays on stdio")

    import uvicorn

    from server import app

    if frozen and sys.platform == "win32":
        threading.Thread(target=_exit_with_app, name="app-watch",
                         daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
