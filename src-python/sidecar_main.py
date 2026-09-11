"""
Entry point for the PyInstaller-frozen sidecar binary.

The dev path stays `python -m uvicorn server:app --port 8765 --reload`;
this module exists only so the frozen exe has a static import root that
PyInstaller can walk (server -> engine.*). Built by
scripts/build_sidecar.py into src-tauri/binaries/, which Tauri bundles as
an external binary and spawns in release builds (see src-tauri/src/main.rs).
"""

from __future__ import annotations

import uvicorn

from server import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
