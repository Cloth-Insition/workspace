"""
Conflict reconciliation — the app-level last-write-wins merge.

Why this exists: libSQL's offline-writes sync does NOT merge. Divergence
(writes on both machines between syncs) makes the second pusher's sync fail
permanently with a server conflict — its local writes are stranded. Verified
empirically against Turso on 2026-09-10; see docs/SYNC-POLICY.md.

So the documented policy — last-write-wins per row on updated_at — is
implemented here and triggered exactly when that conflict error appears:

  1. Under the connection lock, export every syncable row from the stuck
     local replica.
  2. Close it and move its files aside (kept as a timestamped .conflict
     backup — nothing is destroyed).
  3. Pull a fresh replica of the cloud state.
  4. Merge the exported local rows in, row by row: the newer updated_at
     wins; tombstones carry deletions (a deletion is just a write whose
     timestamp competes like any other); on a literal timestamp tie the
     cloud copy wins, deterministically.
  5. Push. If another machine pushed while we merged, that push conflicts
     too — the next sync cycle simply reconciles again on newer state.
  6. Hand the fresh connection back to the app.

Everything here assumes the schema prepared in migrations 001/002: stable
TEXT primary keys, updated_at on every syncing table, tombstones with
content_hash.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from . import db

# Syncable tables and their identity/timestamp columns. tombstones and
# schema_migrations are handled specially below.
TABLES = {
    "trades": "id",
    "kv": "key",
    "lists": "id",
    "list_items": "id",
}

# How many .conflict backups of a stuck replica to keep around.
KEEP_CONFLICT_BACKUPS = 3


def is_conflict_error(err: str | None) -> bool:
    return bool(err) and "conflict" in err.lower()


def _rows_as_dicts(conn, table: str) -> list[dict]:
    cur = conn.execute(f'SELECT * FROM "{table}"')
    rows = cur.fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def _export_local(conn) -> dict[str, list[dict]]:
    out = {}
    for t in list(TABLES) + ["tombstones", "schema_migrations"]:
        out[t] = _rows_as_dicts(conn, t)
    return out


def _move_aside(path: Path) -> list[tuple[Path, Path]]:
    """Move the replica file and its sidecars to a .conflict-<stamp> name.
    Returns the moves so a failed pull can undo them."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moves = []
    for suffix in ("", "-wal", "-shm", "-info"):
        src = Path(str(path) + suffix)
        if src.exists():
            dst = Path(str(path) + f".conflict-{stamp}" + suffix)
            src.rename(dst)
            moves.append((src, dst))
    _prune_backups(path)
    return moves


def _prune_backups(path: Path) -> None:
    try:
        stamps = sorted({
            p.name.split(".conflict-")[1].split("-wal")[0].split("-shm")[0].split("-info")[0]
            for p in path.parent.glob(path.name + ".conflict-*")
        })
        for stamp in stamps[:-KEEP_CONFLICT_BACKUPS]:
            for p in path.parent.glob(path.name + f".conflict-{stamp}*"):
                p.unlink(missing_ok=True)
    except Exception:
        pass


def _undo_moves(moves: list[tuple[Path, Path]]) -> None:
    for src, dst in moves:
        try:
            dst.rename(src)
        except Exception:
            pass


def _merge(fresh, local: dict[str, list[dict]]) -> dict[str, int]:
    """Merge exported local rows into the freshly pulled cloud replica.
    Returns counts of applied local wins per table (for the log)."""
    stats: dict[str, int] = {}

    # Tombstones first: union both sides, newest deleted_at per (table, row).
    cloud_tombs = {(r["table_name"], r["row_id"]): r
                   for r in _rows_as_dicts(fresh, "tombstones")}
    tombs = dict(cloud_tombs)
    for r in local["tombstones"]:
        key = (r["table_name"], r["row_id"])
        if key not in tombs or (r["deleted_at"] or "") > (tombs[key]["deleted_at"] or ""):
            tombs[key] = r

    dropped_tombs: set[tuple[str, str]] = set()

    for table, pk in TABLES.items():
        cloud = {r[pk]: r for r in _rows_as_dicts(fresh, table)}
        loc = {r[pk]: r for r in local[table]}
        applied = 0

        for rid in set(cloud) | set(loc):
            c, l = cloud.get(rid), loc.get(rid)
            c_ts = (c or {}).get("updated_at") or ""
            l_ts = (l or {}).get("updated_at") or ""
            tomb = tombs.get((table, rid))
            d_ts = (tomb or {}).get("deleted_at") or ""

            # Highest timestamp wins. Alive beats dead on a tie (never lose
            # data to an equal-time delete); cloud beats local on an
            # alive-alive tie (deterministic across both machines).
            best_alive = max(c_ts, l_ts)
            if tomb and d_ts > best_alive:
                # Deletion wins: make sure the row is gone from the fresh DB.
                if c is not None:
                    fresh.execute(f'DELETE FROM "{table}" WHERE "{pk}" = ?', (rid,))
                    applied += 1
                continue
            if tomb:
                # A live version outranks the tombstone — the row was
                # legitimately (re)written after the delete. Drop the marker.
                dropped_tombs.add((table, rid))

            if l is None or c_ts >= l_ts:
                continue  # cloud copy stands (or only cloud has it)

            # Local wins: upsert the exported row with its own updated_at
            # (the auto-stamp triggers respect explicit values).
            cols = list(l.keys())
            placeholders = ", ".join("?" for _ in cols)
            col_list = ", ".join(f'"{k}"' for k in cols)
            assignments = ", ".join(f'"{k}" = excluded."{k}"' for k in cols if k != pk)
            fresh.execute(
                f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) '
                f'ON CONFLICT("{pk}") DO UPDATE SET {assignments}',
                [l[k] for k in cols],
            )
            applied += 1
        stats[table] = applied

    # Write back the merged tombstone set.
    fresh.execute("DELETE FROM tombstones")
    for (tname, rid), r in tombs.items():
        if (tname, rid) in dropped_tombs:
            continue
        fresh.execute(
            "INSERT INTO tombstones (table_name, row_id, deleted_at, content_hash) "
            "VALUES (?, ?, ?, ?)",
            (tname, rid, r["deleted_at"], r.get("content_hash")),
        )

    # schema_migrations: union by name (a migration applied locally but not
    # yet pushed must survive the merge).
    have = {r["name"] for r in _rows_as_dicts(fresh, "schema_migrations")}
    for r in local["schema_migrations"]:
        if r["name"] not in have:
            fresh.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (r["name"], r["applied_at"]),
            )
    return stats


def run(conn, lock, swap_conn) -> tuple[bool, str | None]:
    """Full reconciliation of a conflicted replica. Called by the sync
    manager when a sync attempt reports a server conflict.

    conn      — the current (stuck) state connection
    lock      — the app's connection lock; held for the whole operation
    swap_conn — callback installing the replacement connection in ledger_db

    Returns (ok, error). On any failure before the fresh replica is usable,
    the original files are restored and the app keeps running on the stuck
    (but locally consistent) replica.
    """
    path = db.state_db_path()
    with lock:
        try:
            local = _export_local(conn)
        except Exception as exc:
            return False, f"reconcile export failed: {exc}"
        try:
            conn.close()
        except Exception:
            pass
        moves = _move_aside(path)
        try:
            fresh = db.connect_state()  # pulls the cloud state
        except Exception as exc:
            _undo_moves(moves)
            try:
                swap_conn(db.connect_state())
            except Exception as exc2:
                return False, (f"reconcile pull failed AND replica reopen failed: "
                               f"{exc} / {exc2}")
            return False, f"reconcile pull failed (replica restored): {exc}"

        try:
            stats = _merge(fresh, local)
            fresh.commit()
        except Exception as exc:
            # Merge failed: abandon the fresh copy, restore the original.
            try:
                fresh.close()
            except Exception:
                pass
            for suffix in ("", "-wal", "-shm", "-info"):
                Path(str(path) + suffix).unlink(missing_ok=True)
            _undo_moves(moves)
            try:
                swap_conn(db.connect_state())
            except Exception:
                pass
            return False, f"reconcile merge failed (replica restored): {exc}"

        swap_conn(fresh)

    # Push the merged state. The server side of a just-conflicted session
    # can transiently answer 503 "database is locked" for a few seconds, so
    # retry briefly; a genuine new conflict (another machine pushed while we
    # merged) is left for the next sync cycle, which reconciles again on the
    # newer state.
    ok = False
    err: str | None = None
    for attempt in range(4):
        ok, err = db.try_sync(fresh)
        if ok or is_conflict_error(err):
            break
        time.sleep(2 + attempt * 2)
    summary = ", ".join(f"{t}:{n}" for t, n in stats.items() if n) or "no local wins"
    print(f"[reconcile] merged local changes ({summary}); push "
          f"{'ok' if ok else 'deferred: ' + str(err)}", file=sys.stderr, flush=True)
    try:
        cache = db.connect_cache()
        with cache:
            cache.execute(
                "INSERT INTO kv (key, value) VALUES ('sync:last_reconcile_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(int(time.time())),))
        cache.close()
    except Exception:
        pass
    return ok, err
