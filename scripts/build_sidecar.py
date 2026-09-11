"""
Freeze the FastAPI sidecar into the single exe Tauri bundles.

Output: src-tauri/binaries/workspace-sidecar-x86_64-pc-windows-msvc.exe
(the target-triple suffix is Tauri's externalBin naming convention; Tauri
strips it when bundling). Run before `npm run tauri build`:

    cd src-python
    .venv/Scripts/python ../scripts/build_sidecar.py

Notes
  * --onefile: one exe, extracted to a temp dir at launch (~2s startup,
    absorbed by the app's existing health-gate boot state).
  * Console build, not --noconsole: the shell plugin spawns it with
    CREATE_NO_WINDOW so nothing flashes, and a console build keeps real
    stdio for the [sidecar] log forwarding in main.rs. A --noconsole build
    can end up with sys.stderr = None and crash on the first print.
  * PyInstaller work/spec files go under src-python/build (gitignored).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src-python"
OUT = REPO / "src-tauri" / "binaries"
TRIPLE = "x86_64-pc-windows-msvc"


def main() -> int:
    if platform.system() != "Windows":
        print("this build script targets Windows (adjust TRIPLE for other hosts)")
        return 1
    work = SRC / "build"
    r = subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--name", "workspace-sidecar",
        "--distpath", str(work / "dist"),
        "--workpath", str(work / "work"),
        "--specpath", str(work),
        "--noconfirm",
        "--clean",
        str(SRC / "sidecar_main.py"),
    ], cwd=SRC)
    if r.returncode != 0:
        return r.returncode

    exe = work / "dist" / "workspace-sidecar.exe"
    if not exe.exists():
        print(f"expected output missing: {exe}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"workspace-sidecar-{TRIPLE}.exe"
    shutil.copy2(exe, dest)
    print(f"\nsidecar built: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
