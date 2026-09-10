"""
Ledger persistence.

Replaces the browser's window.storage. The original Ledger stored four things
under string keys: the trades array, an account-snapshots array, the SPY price
cache, and a 'seeded' flag. We keep that exact surface so the frontend's
load/save functions map one-to-one — only their bodies change from
window.storage calls to fetch() calls against these endpoints.

Trades are stored as proper rows (not a JSON blob) so that later the workspace
can query them — but the API hands the frontend back the same array shape it
already expects, so nothing in the component's logic has to change.

Storage backend: engine.db picks it (see that module's docstring). With Turso
credentials configured, state lives in a libSQL synced database that
replicates across machines; without them, the original plain-SQLite
workspace.db, exactly as before. Machine-local caches (kv keys matching
db.LOCAL_ONLY_KEY_PREFIXES — rotation/levels scan caches, the SPY price
cache) are routed to a separate never-synced cache file in both modes.

Sync-aware write discipline (the conflict policy depends on it):

  * save_trades DIFFS the incoming array against stored rows instead of
    rewriting the table. Only genuinely changed rows are written, so
    updated_at (stamped by the migration-001 triggers) means what the
    last-write-wins merge in engine/reconcile.py needs it to mean:
    "when a human last touched THIS row".
  * Deletions insert a tombstone carrying a content hash of the removed
    row. A deleted row would otherwise resurrect when a machine with the
    old array in memory saves; the hash distinguishes that stale re-insert
    (identical content -> blocked) from the user deliberately re-logging a
    trade under the same ticker-date id (different content -> allowed, and
    the tombstone is cleared).
  * Writes that change nothing are skipped entirely (including set_kv with
    an identical value) so no timestamp churns and no sync is provoked.

Schema note: migrations 001/002 added updated_at + triggers, tombstones and
content_hash. The DDL here still creates the pre-migration shape on a
brand-new empty database — run the migration scripts after first creation on
a fresh machine (the seeded/synced path already carries the migrated schema).
"""

from __future__ import annotations

import json
import threading
import time

from . import db

# One connection, guarded by a lock. SQLite handles concurrent reads fine but
# the sidecar is single-process and this keeps writes clean.
_lock = threading.Lock()
_conn = None


def _connect():
    global _conn
    if _conn is None:
        conn = db.connect_state()
        _init(conn)
        _conn = conn
        # One-time move of cache-prefixed kv rows into the local cache store.
        db.migrate_cache_keys(_conn, _lock)
    return _conn


def swap_connection(new_conn) -> None:
    """Install a replacement state connection (used by reconcile after it
    rebuilds the replica). Caller coordinates locking."""
    global _conn
    _conn = new_conn


def _init(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id                    TEXT PRIMARY KEY,
            ticker                TEXT NOT NULL,
            entryDate             TEXT NOT NULL,
            exitDate              TEXT,
            entryPrice            REAL NOT NULL,
            exitPrice             REAL,
            accountValueAtEntry   REAL,
            positionDollars       REAL,
            conviction            INTEGER,
            scaledInOut           INTEGER,
            followedRules         INTEGER,
            notes                 TEXT,
            exitReason            TEXT,
            extra                 TEXT,          -- JSON catch-all for any fields
                                                 -- the frontend adds later
            seq                   INTEGER        -- preserves insertion order
        );

        CREATE TABLE IF NOT EXISTS kv (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.commit()


# Columns we store as real columns; everything else on a trade goes to `extra`.
_TRADE_COLS = [
    "id", "ticker", "entryDate", "exitDate", "entryPrice", "exitPrice",
    "accountValueAtEntry", "positionDollars", "conviction", "scaledInOut",
    "followedRules", "notes", "exitReason",
]
_BOOL_COLS = {"scaledInOut", "followedRules"}


def _row_to_trade(row) -> dict:
    t: dict = {}
    for col in _TRADE_COLS:
        v = row[col]
        if col in _BOOL_COLS:
            v = bool(v) if v is not None else None
        t[col] = v
    extra = row["extra"]
    if extra:
        try:
            t.update(json.loads(extra))
        except Exception:
            pass
    return t


def _normalize_trade(t: dict) -> dict:
    """Canonical comparable form of a trade dict (frontend- or DB-sourced):
    every known column present (bools as bool/None), extras merged flat.
    seq is positional and excluded — reorderings are handled separately."""
    out: dict = {}
    for col in _TRADE_COLS:
        v = t.get(col)
        if col in _BOOL_COLS:
            v = bool(v) if v is not None else None
        out[col] = v
    for k, v in t.items():
        if k not in _TRADE_COLS and k not in ("seq", "updated_at"):
            out[k] = v
    return out


def _trade_insert(conn, t: dict, seq: int) -> None:
    known = {k: t.get(k) for k in _TRADE_COLS}
    for b in _BOOL_COLS:
        if known[b] is not None:
            known[b] = 1 if known[b] else 0
    extra = {k: v for k, v in t.items()
             if k not in _TRADE_COLS and k not in ("seq", "updated_at")}
    conn.execute(
        f"""INSERT INTO trades
            ({', '.join(_TRADE_COLS)}, extra, seq)
            VALUES ({', '.join('?' for _ in _TRADE_COLS)}, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
            {', '.join(f'{c} = excluded.{c}' for c in _TRADE_COLS if c != 'id')},
            extra = excluded.extra, seq = excluded.seq""",
        [known[c] for c in _TRADE_COLS]
        + [json.dumps(extra) if extra else None, seq],
    )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) \
        + f".{int(time.time()*1000) % 1000:03d}Z"


def load_trades() -> list[dict] | None:
    """Return the trades array in insertion order, or None if never seeded."""
    conn = _connect()
    with _lock:
        cur = conn.execute("SELECT * FROM trades ORDER BY seq ASC")
        rows = cur.fetchall()
    if not rows:
        # Distinguish 'empty because never seeded' from 'empty by choice' via kv.
        return [] if get_kv("ledger:initialized") else None
    return [_row_to_trade(r) for r in rows]


def save_trades(trades: list[dict]) -> bool:
    """Persist the frontend's full trades array by diffing it against the
    stored rows: insert the new, update the changed, delete-and-tombstone
    the removed, and leave untouched rows alone so their updated_at
    (and therefore the sync conflict policy) stays truthful."""
    conn = _connect()
    with _lock:
        stored_rows = conn.execute("SELECT * FROM trades").fetchall()
        stored: dict[str, dict] = {}
        stored_seq: dict[str, int] = {}
        for r in stored_rows:
            t = _row_to_trade(r)
            stored[t["id"]] = _normalize_trade(t)
            stored_seq[t["id"]] = r["seq"]

        tomb_rows = conn.execute(
            "SELECT row_id, content_hash FROM tombstones WHERE table_name='trades'"
        ).fetchall()
        tombs = {r["row_id"]: r["content_hash"] for r in tomb_rows}

        incoming_ids: set[str] = set()
        for seq, t in enumerate(trades):
            tid = t.get("id")
            if not tid:
                continue  # a trade without an id has no stable identity; skip
            incoming_ids.add(tid)
            norm = _normalize_trade(t)
            if tid in stored:
                if stored[tid] == norm and stored_seq[tid] == seq:
                    continue  # untouched — updated_at stays put
                _trade_insert(conn, t, seq)  # upsert; trigger bumps updated_at
            else:
                if tid in tombs and tombs[tid] == db.row_content_hash(norm):
                    # Identical content to what was deliberately deleted:
                    # this is a stale frontend array resurrecting a dead row.
                    continue
                _trade_insert(conn, t, seq)
                if tid in tombs:
                    # Deliberate re-add under a recycled id — clear the marker.
                    conn.execute(
                        "DELETE FROM tombstones WHERE table_name='trades' AND row_id=?",
                        (tid,))

        for tid, norm in stored.items():
            if tid not in incoming_ids:
                conn.execute("DELETE FROM trades WHERE id = ?", (tid,))
                conn.execute(
                    "INSERT INTO tombstones (table_name, row_id, deleted_at, content_hash) "
                    "VALUES ('trades', ?, ?, ?) "
                    "ON CONFLICT(table_name, row_id) DO UPDATE SET "
                    "deleted_at = excluded.deleted_at, "
                    "content_hash = excluded.content_hash",
                    (tid, _now_iso(), db.row_content_hash(norm)))

        # Mark initialized (write once — rewriting it every save would churn
        # the row's updated_at and provoke pointless syncs). Inline, not via
        # set_kv(): that would re-acquire _lock on this thread and deadlock.
        row = conn.execute(
            "SELECT value FROM kv WHERE key = 'ledger:initialized'").fetchone()
        if not row or row["value"] != "true":
            conn.execute(
                "INSERT INTO kv (key, value) VALUES ('ledger:initialized', 'true') "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        conn.commit()
    return True


# ---- Generic key/value, for snapshots, SPY cache, seeded flag ----
# Cache-prefixed keys go to the never-synced local cache DB; real state
# stays in the (possibly synced) state DB.

def get_kv(key: str) -> str | None:
    if db.is_local_only_key(key):
        cache = db.connect_cache()
        try:
            row = cache.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        finally:
            cache.close()
        return row["value"] if row else None
    conn = _connect()
    with _lock:
        cur = conn.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = cur.fetchone()
    return row["value"] if row else None


def set_kv(key: str, value: str) -> None:
    if db.is_local_only_key(key):
        cache = db.connect_cache()
        try:
            with cache:
                cache.execute(
                    "INSERT INTO kv (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
        finally:
            cache.close()
        return
    conn = _connect()
    with _lock:
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row and row["value"] == value:
            return  # unchanged — don't churn updated_at / provoke a sync
        conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
