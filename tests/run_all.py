"""
Test suite runner. From src-python, with the venv python:

    .venv/Scripts/python ../tests/run_all.py            # everything
    .venv/Scripts/python ../tests/run_all.py --offline  # no-network subset

Network tests hit the real Turso database using disposable test rows
(ids test-*) that each test creates, removes, and verifies gone. They need
credentials in src-python/.env and an internet connection, and they leave
the cloud content exactly as they found it.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC_PYTHON = HERE.parent / "src-python"

OFFLINE_TESTS = ["test_migrations.py", "test_fallback.py"]
NETWORK_TESTS = ["test_round_trip.py", "test_offline.py",
                 "test_conflict_reconcile.py", "test_replica_repair.py",
                 "test_stats_regression.py"]


def main() -> int:
    offline_only = "--offline" in sys.argv
    tests = OFFLINE_TESTS + ([] if offline_only else NETWORK_TESTS)
    results: list[tuple[str, bool, float]] = []
    for name in tests:
        print(f"\n{'='*60}\n{name}\n{'='*60}")
        t0 = time.time()
        r = subprocess.run([sys.executable, str(HERE / name)], cwd=SRC_PYTHON)
        results.append((name, r.returncode == 0, time.time() - t0))

    print(f"\n{'='*60}\nSUMMARY\n{'='*60}")
    failed = 0
    for name, ok, dt in results:
        print(f"  {'PASS' if ok else 'FAIL':<6} {name:<32} {dt:6.1f}s")
        failed += 0 if ok else 1
    if offline_only:
        print("  (network tests skipped: --offline)")
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
