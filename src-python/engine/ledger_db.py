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

Schema note: migration 001 added updated_at columns + auto-stamp triggers
and the tombstones table. The DDL here still creates the pre-migration
shape on a brand-new empty database — run scripts/migrate_001_sync_prep.py
after first creation on a fresh machine (the seeded/synced path already
carries the migrated schema).
"""

from __future__ import annotations

import json
import threading

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
    """Replace the whole trades table with the given array (last-write-wins).

    Mirrors the original saveTrades(trades) which overwrote the stored array.
    Splitting known columns from extras keeps the rows queryable without
    constraining what the frontend can attach to a trade.
    """
    conn = _connect()
    with _lock:
        conn.execute("DELETE FROM trades")
        for seq, t in enumerate(trades):
            known = {k: t.get(k) for k in _TRADE_COLS}
            for b in _BOOL_COLS:
                if known[b] is not None:
                    known[b] = 1 if known[b] else 0
            extra = {k: v for k, v in t.items() if k not in _TRADE_COLS}
            conn.execute(
                f"""INSERT INTO trades
                    ({', '.join(_TRADE_COLS)}, extra, seq)
                    VALUES ({', '.join('?' for _ in _TRADE_COLS)}, ?, ?)""",
                [known[c] for c in _TRADE_COLS]
                + [json.dumps(extra) if extra else None, seq],
            )
        # Mark initialized inline — do NOT call set_kv() here, it would try to
        # re-acquire _lock on this same thread and deadlock.
        conn.execute(
            "INSERT INTO kv (key, value) VALUES ('ledger:initialized', 'true') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
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
        conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
