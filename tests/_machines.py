"""
Shared plumbing for the sync test suite: run a test step in a subprocess
that impersonates one "machine" (its own synced-replica path via
WORKSPACE_SYNCED_DB_PATH), optionally with an unreachable sync host to
simulate being offline.

Each test file declares STEPS = {name: fn} and calls dispatch(main) — the
file re-invokes itself with `--step <name>` per machine so every step runs
the real engine code path with clean module state.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SRC_PYTHON = Path(__file__).resolve().parent.parent / "src-python"
BAD_URL = "libsql://offline-test-nonexistent-host.turso.io"


def engine():
    sys.path.insert(0, str(SRC_PYTHON))
    from engine import db, ledger_db, reconcile
    return db, ledger_db, reconcile


def run_step(test_file: str, workdir: Path, step: str, machine: str,
             offline: bool = False) -> None:
    (workdir / machine).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["WORKSPACE_SYNCED_DB_PATH"] = str(workdir / machine / "synced.db")
    if offline:
        env["TURSO_DATABASE_URL"] = BAD_URL
        env["TURSO_AUTH_TOKEN"] = "dummy"
    r = subprocess.run([sys.executable, test_file, "--step", step],
                       env=env, cwd=SRC_PYTHON)
    if r.returncode != 0:
        print(f"STEP FAILED: {step} (machine {machine})")
        sys.exit(1)


def dispatch(steps: dict, main_fn) -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--step":
        steps[sys.argv[2]]()
        return 0
    return main_fn()
