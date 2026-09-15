"""
Entry point for the PyInstaller-frozen sidecar binary.

The dev path stays `python -m uvicorn server:app --port 8765 --reload`;
this module exists only so the frozen exe has a static import root that
PyInstaller can walk (server -> engine.*). Built by
scripts/build_sidecar.py into src-tauri/binaries/, which Tauri bundles as
an external binary and spawns in release builds (see src-tauri/src/main.rs).

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

import uvicorn

from server import app

PARENT_POLL_SECONDS = 3


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


def _watched_pid() -> int | None:
    raw = os.environ.get("WORKSPACE_APP_PID", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    try:
        ppid = os.getppid()
    except Exception:
        return None
    return ppid if ppid > 0 else None


def _exit_with_app() -> None:
    """Exit when the app that launched us does.

    os._exit rather than a graceful shutdown: the app is already gone,
    nothing is waiting on a clean response, and the point is to release the
    port immediately. Sync state is durable — every write is committed
    before its response returns, and unsynced local changes reconcile on
    the next launch.
    """
    pid = _watched_pid()
    if pid is None:
        return
    while True:
        time.sleep(PARENT_POLL_SECONDS)
        try:
            if not _process_alive(pid):
                print(f"[sidecar] app process {pid} gone — exiting",
                      file=sys.stderr, flush=True)
                os._exit(0)
        except Exception:
            return  # never let the watchdog itself take the sidecar down


if __name__ == "__main__":
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        threading.Thread(target=_exit_with_app, name="app-watch",
                         daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
