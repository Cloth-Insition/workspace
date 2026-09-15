"""
Entry point for the PyInstaller-frozen sidecar binary.

The dev path stays `python -m uvicorn server:app --port 8765 --reload`;
this module exists only so the frozen exe has a static import root that
PyInstaller can walk (server -> engine.*). Built by
scripts/build_sidecar.py into src-tauri/binaries/, which Tauri bundles as
an external binary and spawns in release builds (see src-tauri/src/main.rs).

Orphan guard: a PyInstaller one-file build runs as two processes — a
bootloader that extracts the payload, and the child that actually runs
this code. Killing the bootloader (which is what Tauri does when the app
exits) leaves the child alive, still holding port 8765, so the NEXT launch
of the app cannot bind and the backend silently stays the old one. So the
child watches its parent and exits when the parent goes away.
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


def _exit_with_parent() -> None:
    """Exit when the process that launched us does.

    os._exit rather than a graceful shutdown: the parent is already gone,
    nothing is waiting on a clean response, and the point is to release the
    port immediately. Sync state is durable — every write is committed
    before its response returns, and unsynced local changes reconcile on
    the next launch.
    """
    try:
        ppid = os.getppid()
    except Exception:
        return
    if ppid <= 0:
        return
    while True:
        time.sleep(PARENT_POLL_SECONDS)
        try:
            if not _process_alive(ppid):
                print("[sidecar] parent process gone — exiting",
                      file=sys.stderr, flush=True)
                os._exit(0)
        except Exception:
            return  # never let the watchdog itself take the sidecar down


if __name__ == "__main__":
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        threading.Thread(target=_exit_with_parent, name="parent-watch",
                         daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
