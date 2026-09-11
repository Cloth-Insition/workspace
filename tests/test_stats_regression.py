"""
Statistics regression: the same trades must come out of the old storage and
the new, and the statistics engines must produce identical output on both.

"Before migration" is reconstructed live: a copy of workspace.db with both
migrations reverted, read through the plain-sqlite local mode — the exact
pre-project storage path. "After" is the current libSQL synced replica.
The trade arrays must be deep-equal (order included), and alpha + luck —
both deterministic; no sampling anywhere in the engine — must return
byte-identical results on the two arrays.

Needs network (beta/rho estimation fetches market history via yfinance).
A rate-limited fetch fails loudly per the engine's own convention — rerun
later rather than trusting a NaN-poisoned result.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC_PYTHON = REPO / "src-python"
LIVE = SRC_PYTHON / "engine" / "workspace.db"

sys.path.insert(0, str(REPO / "scripts"))

LUCK_SAMPLE = 5  # closed+iv trades fed to luck (keeps yfinance polite)


def dump_trades(out: Path) -> None:
    sys.path.insert(0, str(SRC_PYTHON))
    from engine import ledger_db
    out.write_text(json.dumps(ledger_db.load_trades(), sort_keys=True))


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--dump":
        dump_trades(Path(sys.argv[2]))
        return 0

    work = Path(tempfile.mkdtemp(prefix="stats-regress-"))
    try:
        # Old storage: revert both migrations on a copy.
        import importlib
        import sqlite3
        mig1 = importlib.import_module("migrate_001_sync_prep")
        mig2 = importlib.import_module("migrate_002_tombstone_hash")
        old_db = work / "old.db"
        shutil.copy(LIVE, old_db)
        for fn in (mig2.down, mig1.down):
            conn = sqlite3.connect(old_db)
            conn.execute("PRAGMA foreign_keys = OFF")
            fn(conn)
            conn.close()

        def dump(machine_env: dict, out: Path):
            env = dict(os.environ) | machine_env
            r = subprocess.run([sys.executable, __file__, "--dump", str(out)],
                               env=env, cwd=SRC_PYTHON)
            assert r.returncode == 0, "dump subprocess failed"
            return json.loads(out.read_text())

        old_trades = dump({"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": "",
                           "WORKSPACE_DB_PATH": str(old_db),
                           "WORKSPACE_CACHE_DB_PATH": str(work / "c1.db")},
                          work / "old.json")
        new_trades = dump({}, work / "new.json")  # default env: synced replica

        assert old_trades == new_trades, (
            "trade arrays differ between pre-migration storage and the "
            "synced replica")
        print(f"trade arrays identical: {len(new_trades)} trades, "
              "pre-migration plain SQLite vs synced libSQL replica")

        # Deterministic statistics on both arrays must match exactly.
        sys.path.insert(0, str(SRC_PYTHON))
        from engine import alpha, luck

        # The engines fetch market history live on every call, and two calls
        # seconds apart can see today's bar tick — that's market noise, not a
        # storage regression. Memoize the fetcher (test-only wrapper; the
        # statistics code itself is untouched) so both runs see identical
        # data and the comparison isolates exactly the storage effect.
        _memo: dict = {}
        _real_fetch = luck._fetch_closes

        def _cached_fetch(ticker, lookback=luck.BETA_LOOKBACK):
            key = (ticker, lookback)
            if key not in _memo:
                _memo[key] = _real_fetch(ticker, lookback)
            return _memo[key]

        luck._fetch_closes = _cached_fetch
        luck.fetch_closes = _cached_fetch
        alpha.fetch_closes = _cached_fetch

        a_old = alpha.compute_alpha(old_trades)
        a_new = alpha.compute_alpha(new_trades)
        assert json.dumps(a_old, sort_keys=True, default=str) == \
               json.dumps(a_new, sort_keys=True, default=str), "alpha output differs"
        print(f"alpha identical on both arrays "
              f"(keys: {sorted(a_new)[:6]}{'...' if len(a_new) > 6 else ''})")

        def luck_input(trades):
            rows = []
            for t in trades:
                iv = t.get("iv")
                if t.get("exitDate") and t.get("exitPrice") is not None and iv:
                    rows.append({
                        "ticker": t["ticker"], "entryDate": t["entryDate"],
                        "exitDate": t["exitDate"], "entryPrice": t["entryPrice"],
                        "exitPrice": t["exitPrice"],
                        "iv": iv / 100 if iv > 3 else iv,
                    })
                if len(rows) == LUCK_SAMPLE:
                    break
            return rows

        li_old, li_new = luck_input(old_trades), luck_input(new_trades)
        assert li_old == li_new and li_old, f"luck inputs differ or empty ({len(li_old)})"
        l_old = luck.calculate(li_old)
        l_new = luck.calculate(li_new)
        assert json.dumps(l_old, sort_keys=True, default=str) == \
               json.dumps(l_new, sort_keys=True, default=str), "luck output differs"
        print(f"luck identical on both arrays ({len(li_new)} trades scored)")

        print("\nSTATISTICS REGRESSION PASSED")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
