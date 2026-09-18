"""
Statistics regression across the sync migration: nothing present at migration
time was lost or altered on the way into the synced replica, and the
statistics engines see those trades identically.

"Before migration" is reconstructed live: a copy of workspace.db -- the frozen
rollback copy -- with both migrations reverted on the copy, read through the
plain-sqlite local mode, the exact pre-project storage path. "After" is the
current libSQL synced replica, read only through ledger_db in a subprocess.

Why not equality. This used to assert the two trade arrays were identical,
which holds for exactly as long as nothing is logged after migrating. The
rollback copy is frozen by design, so the first trade logged through normal
use made the arrays differ and the test failed against a perfectly healthy
replica (2026-09-18: 40 trades in the rollback copy, 45 in the replica, all 40
intact). The invariant that matters is containment:

  1. every trade in the rollback copy exists in the replica
  2. each of those is identical field for field, TYPE-STRICT. 1, 1.0 and True
     all compare equal under ==, and `iv` genuinely holds a mix of ints and
     floats, so == would pass a storage layer that quietly changed types
  3. they keep their relative order
  4. alpha and luck -- both deterministic, no sampling -- return byte-identical
     output on the rollback trades and on the replica's copy of those trades

Trades logged after migration are reported, not failed.

Deliberately editing or deleting a PRE-migration trade will also fail this.
From here a chosen edit is indistinguishable from corruption; the failure
names the trade and the field, and if the change was yours it is correct.

Proving it can fail -- CLAUDE.md requires a regression test be shown to fail
against a bad case before it is trusted:

    .venv/Scripts/python ../tests/test_stats_regression.py --prove-negative

corrupts the TEMP copy four ways (a trade the replica lacks, an altered
exitPrice, a reordering, an int turned float) and requires each run to fail
with the matching message. Neither real store is ever written: the replica is
only read, and the rollback copy is only copied.

Needs network (beta/rho estimation fetches market history via yfinance).
A rate-limited fetch fails loudly per the engine's own convention -- rerun
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

# --prove-negative: each corruption and the message its failure must carry.
NEGATIVE_CASES = {
    "lose": "missing from the replica",
    "alter": "altered",
    "reorder": "out of order",
    "retype": "(int)",
}


def check(ok: bool, msg: str) -> None:
    """A failure that survives `python -O`, which strips bare asserts and
    would turn every check here into a silent pass."""
    if not ok:
        raise AssertionError(msg)


def canon(t: dict) -> str:
    """Type-strict identity for a trade: 32 and 32.0 differ here, as do
    True and 1, where == would call them equal."""
    return json.dumps(t, sort_keys=True)


def dump_trades(out: Path) -> None:
    sys.path.insert(0, str(SRC_PYTHON))
    from engine import ledger_db
    out.write_text(json.dumps(ledger_db.load_trades(), sort_keys=True),
                   encoding="utf-8")


def corrupt_copy(db: Path, work: Path, mode: str) -> None:
    """Damage the reverted TEMP copy so the comparison has something to catch.

    Only ever the temp copy -- guarded below, because the same code pointed at
    the real rollback copy would destroy the thing it exists to protect. The
    replica is never opened here at all.
    """
    import sqlite3

    db = db.resolve()
    check(db.parent == work.resolve() and db != LIVE.resolve(),
          f"refusing to corrupt anything but the temp copy: {db}")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM trades ORDER BY seq").fetchall()
    check(len(rows) >= 6, "too few trades to corrupt meaningfully")

    if mode == "lose":
        # A trade the rollback copy has and the replica does not: the shape
        # of a pre-migration trade lost in transit. (Deleting from the
        # replica would be the literal case, and the replica is never
        # written, so the same asymmetry is produced from this side.)
        r = dict(rows[0])
        r["id"] = "test-negative-lost-trade"
        r["seq"] = max(x["seq"] for x in rows) + 1
        cols = ", ".join(r)
        marks = ", ".join("?" for _ in r)
        conn.execute(f"INSERT INTO trades ({cols}) VALUES ({marks})",
                     list(r.values()))
    elif mode == "alter":
        target = next(x for x in rows[5:] if x["exitPrice"] is not None)
        conn.execute("UPDATE trades SET exitPrice = exitPrice + 1.0 "
                     "WHERE id = ?", (target["id"],))
    elif mode == "reorder":
        a, b = rows[0], rows[1]
        conn.execute("UPDATE trades SET seq = ? WHERE id = ?", (-1, a["id"]))
        conn.execute("UPDATE trades SET seq = ? WHERE id = ?",
                     (a["seq"], b["id"]))
        conn.execute("UPDATE trades SET seq = ? WHERE id = ?",
                     (b["seq"], a["id"]))
    elif mode == "retype":
        # Same number, different type: invisible to ==, fatal to anything
        # that serialises it. Lives in the JSON `extra` column.
        for x in rows:
            extra = json.loads(x["extra"]) if x["extra"] else {}
            iv = extra.get("iv")
            if isinstance(iv, int) and not isinstance(iv, bool):
                extra["iv"] = float(iv)
                conn.execute("UPDATE trades SET extra = ? WHERE id = ?",
                             (json.dumps(extra), x["id"]))
                break
        else:
            raise AssertionError("no integer iv found to retype -- the "
                                 "negative case cannot be constructed")
    else:
        raise AssertionError(f"unknown corruption mode {mode!r}")
    conn.commit()
    conn.close()


def compare_stores(old: list[dict], new: list[dict]) -> list[dict]:
    """Check invariants 1-3. Returns the replica's copy of the pre-migration
    trades, in the replica's own order, for the engine comparison."""
    new_by_id = {t["id"]: t for t in new}
    old_ids = [t["id"] for t in old]
    old_set = set(old_ids)
    problems: list[str] = []

    missing = [t for t in old if t["id"] not in new_by_id]
    if missing:
        problems.append(
            f"{len(missing)} pre-migration trade(s) missing from the replica: "
            + ", ".join(f"{t['ticker']} {t['entryDate']} [{t['id']}]"
                        for t in missing))

    for t in old:
        n = new_by_id.get(t["id"])
        if n is None or canon(t) == canon(n):
            continue
        diffs = []
        for k in sorted(set(t) | set(n)):
            a, b = t.get(k, "<absent>"), n.get(k, "<absent>")
            if json.dumps(a) != json.dumps(b):
                diffs.append(f"{k}: {a!r} ({type(a).__name__}) -> "
                             f"{b!r} ({type(b).__name__})")
        problems.append(f"pre-migration trade altered, {t['ticker']} "
                        f"{t['entryDate']} [{t['id']}]: " + "; ".join(diffs))

    present = [i for i in old_ids if i in new_by_id]
    in_replica_order = [t["id"] for t in new if t["id"] in old_set]
    if in_replica_order != present:
        first = next(k for k, (x, y) in enumerate(zip(present, in_replica_order))
                     if x != y)
        problems.append(
            "pre-migration trades are out of order in the replica, first at "
            f"position {first}: expected {present[first]}, "
            f"found {in_replica_order[first]}")

    check(not problems, "\n  ".join(["replica does not contain the "
                                     "pre-migration trades intact:"] + problems))

    later = [t for t in new if t["id"] not in old_set]
    print(f"all {len(old)} pre-migration trades present, identical "
          "(type-strict) and in order in the synced replica")
    if later:
        print(f"{len(later)} trade(s) logged since migration (expected, not "
              "compared): "
              + ", ".join(f"{t['ticker']} {t['entryDate']}" for t in later))
    return [t for t in new if t["id"] in old_set]


def prove_negative() -> int:
    """Run the real test once per corruption; every run must fail, and fail
    for the right reason."""
    ok_all = True
    for mode, needle in NEGATIVE_CASES.items():
        r = subprocess.run([sys.executable, __file__, "--corrupt", mode],
                           cwd=SRC_PYTHON, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        ok = r.returncode != 0 and needle in out
        ok_all &= ok
        line = next((ln.strip() for ln in out.splitlines()
                     if needle in ln), "(expected message not found)")
        print(f"  {'CAUGHT' if ok else 'MISSED'}  {mode:<8} exit {r.returncode}"
              f"  {line[:150]}")
    print("\nNEGATIVE PROOF " + ("PASSED: every corruption was caught"
                                 if ok_all else "FAILED: a corruption got through"))
    return 0 if ok_all else 1


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--dump":
        dump_trades(Path(sys.argv[2]))
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "--prove-negative":
        return prove_negative()
    corrupt = sys.argv[2] if len(sys.argv) >= 3 and sys.argv[1] == "--corrupt" else None

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
        if corrupt:
            corrupt_copy(old_db, work, corrupt)
            print(f"negative case: temp copy corrupted ({corrupt})")

        def dump(machine_env: dict, out: Path):
            env = dict(os.environ) | machine_env
            r = subprocess.run([sys.executable, __file__, "--dump", str(out)],
                               env=env, cwd=SRC_PYTHON)
            check(r.returncode == 0, "dump subprocess failed")
            return json.loads(out.read_text(encoding="utf-8"))

        old_trades = dump({"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": "",
                           "WORKSPACE_DB_PATH": str(old_db),
                           "WORKSPACE_CACHE_DB_PATH": str(work / "c1.db")},
                          work / "old.json")
        new_trades = dump({}, work / "new.json")  # default env: synced replica

        shared = compare_stores(old_trades, new_trades)

        # Deterministic statistics must match exactly between the rollback
        # trades and the replica's copy of them.
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
        a_new = alpha.compute_alpha(shared)
        check(json.dumps(a_old, sort_keys=True, default=str) ==
              json.dumps(a_new, sort_keys=True, default=str),
              "alpha output differs")
        print(f"alpha identical on the pre-migration trades "
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

        li_old, li_new = luck_input(old_trades), luck_input(shared)
        check(li_old == li_new and bool(li_old),
              f"luck inputs differ or empty ({len(li_old)})")
        l_old = luck.calculate(li_old)
        l_new = luck.calculate(li_new)
        check(json.dumps(l_old, sort_keys=True, default=str) ==
              json.dumps(l_new, sort_keys=True, default=str),
              "luck output differs")
        print(f"luck identical on the pre-migration trades "
              f"({len(li_new)} trades scored)")

        print("\nSTATISTICS REGRESSION PASSED")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
