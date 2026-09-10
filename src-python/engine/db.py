"""
Connection layer — the only module that knows which driver the app runs on.

Two modes, decided once at startup from environment / .env:

  * synced  — TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are present. State
    lives in a libSQL "synced database" file (offline=True): reads and
    writes are local, and sync() pushes/pulls against Turso when the
    network allows. Sync failures are catchable and non-fatal.
  * local   — no credentials. State lives in the original plain SQLite
    file via stdlib sqlite3, exactly as before the migration. No network
    is ever touched.

In both modes, machine-local caches (rotation scan, levels scan, SPY price
cache) live in a separate plain-SQLite file that never syncs — they are
big, disposable, per-machine blobs. The split is by kv key prefix, listed
in LOCAL_ONLY_KEY_PREFIXES; ledger_db routes on it.

Environment (set in the shell or src-python/.env — .env is gitignored):

  TURSO_DATABASE_URL        libsql://... (enables synced mode)
  TURSO_AUTH_TOKEN          token for the database
  WORKSPACE_DB_PATH         local-mode state file   (default engine/workspace.db)
  WORKSPACE_SYNCED_DB_PATH  synced-mode state file  (default engine/workspace-synced.db)
  WORKSPACE_CACHE_DB_PATH   cache file              (default engine/local_cache.db)

The synced file is deliberately distinct from workspace.db: libSQL manages
its own sync metadata, and pointing it at the original file risks the
known adopt-existing-database corruption issues. workspace.db stays behind
as the untouched fallback/rollback copy; scripts/seed_synced_db.py copies
its state across once.

libSQL API compatibility note (flagged, not silently absorbed): libsql
connections do not support row_factory / sqlite3.Row. Query code in
ledger_db/lists_db relies on row["column"] access, so synced-mode
connections are wrapped in a thin cursor shim that adds named access via
cursor.description. Local mode keeps genuine sqlite3.Row. Query code is
untouched either way.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
ENV_FILE = ENGINE_DIR.parent / ".env"

LOCAL_ONLY_KEY_PREFIXES = ("rotation:", "levels:", "ledger:spy_cache")


def row_content_hash(d: dict) -> str:
    """Canonical hash of a row's content, for tombstone resurrection checks."""
    import hashlib
    import json
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, default=str).encode()
    ).hexdigest()

# ---------------------------------------------------------------- env

_env_loaded = False


def _load_env() -> None:
    """Fold src-python/.env into os.environ (existing env vars win)."""
    global _env_loaded
    if _env_loaded:
        return
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    # Flag set only after parsing: a concurrent caller re-parses harmlessly
    # (setdefault) instead of returning early against a half-loaded env.
    _env_loaded = True


def _cfg(name: str, default: str) -> str:
    _load_env()
    return os.environ.get(name, default)


def mode() -> str:
    """'synced' when Turso credentials are configured, else 'local'."""
    _load_env()
    if os.environ.get("TURSO_DATABASE_URL") and os.environ.get("TURSO_AUTH_TOKEN"):
        return "synced"
    return "local"


def state_db_path() -> Path:
    if mode() == "synced":
        return Path(_cfg("WORKSPACE_SYNCED_DB_PATH", str(ENGINE_DIR / "workspace-synced.db")))
    return Path(_cfg("WORKSPACE_DB_PATH", str(ENGINE_DIR / "workspace.db")))


def cache_db_path() -> Path:
    return Path(_cfg("WORKSPACE_CACHE_DB_PATH", str(ENGINE_DIR / "local_cache.db")))


# ------------------------------------------- libsql named-row shim

class _Row:
    """Minimal sqlite3.Row stand-in: index and name access over a tuple."""

    __slots__ = ("_vals", "_idx")

    def __init__(self, vals: tuple, idx: dict[str, int]):
        self._vals = vals
        self._idx = idx

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._vals[self._idx[key]]
        return self._vals[key]

    def keys(self):
        return list(self._idx)

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def __repr__(self):
        return f"_Row({dict(zip(self._idx, self._vals))})"


class _CursorShim:
    """Wraps a libsql cursor so fetched rows support row['name']."""

    __slots__ = ("_cur", "_idx")

    def __init__(self, cur):
        self._cur = cur
        self._idx = None

    def _index(self) -> dict[str, int]:
        if self._idx is None:
            desc = self._cur.description or []
            self._idx = {col[0]: i for i, col in enumerate(desc)}
        return self._idx

    def fetchone(self):
        row = self._cur.fetchone()
        return None if row is None else _Row(tuple(row), self._index())

    def fetchall(self):
        idx = None
        out = []
        for row in self._cur.fetchall():
            if idx is None:
                idx = self._index()
            out.append(_Row(tuple(row), idx))
        return out

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size) if size is not None else self._cur.fetchmany()
        idx = self._index()
        return [_Row(tuple(r), idx) for r in rows]

    def __iter__(self):
        idx = self._index()
        for row in self._cur:
            yield _Row(tuple(row), idx)

    def __getattr__(self, name):  # description, lastrowid, rowcount, close...
        return getattr(self._cur, name)


class SyncedConnection:
    """Wraps a libsql connection: named-row cursors + guarded sync()."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        return _CursorShim(self._raw.execute(sql, params))

    def executemany(self, sql, seq):
        return _CursorShim(self._raw.executemany(sql, seq))

    def executescript(self, script):
        return self._raw.executescript(script)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()

    def sync(self):
        """Push/pull against Turso. Raises on failure — callers use
        try_sync() unless they specifically want the error."""
        self._raw.sync()


# ---------------------------------------------------------------- connect

def connect_state():
    """Open the state database for the active mode.

    local  -> sqlite3 connection, row_factory=sqlite3.Row, WAL. Identical
              to pre-migration behaviour.
    synced -> libsql offline-writes connection (wrapped). On a fresh file
              this performs one blocking sync so the schema and data arrive
              before the first query — the only moment synced mode needs
              the network. An already-populated file opens fine offline.
    """
    if mode() == "local":
        conn = sqlite3.connect(state_db_path(), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    import libsql  # only imported in synced mode

    path = state_db_path()
    fresh = not path.exists()
    raw = libsql.connect(
        str(path),
        sync_url=os.environ["TURSO_DATABASE_URL"],
        auth_token=os.environ["TURSO_AUTH_TOKEN"],
        offline=True,
    )
    conn = SyncedConnection(raw)
    try:
        conn.sync()
        _record_sync_attempt(success=True)
    except Exception as exc:
        if fresh:
            conn.close()
            raise RuntimeError(
                "First-time sync failed and no local replica exists yet. "
                "Synced mode needs the network once to pull initial state: "
                f"{exc}"
            ) from exc
        print(f"[db] startup sync failed (continuing on local replica): {exc}",
              file=sys.stderr, flush=True)
        _record_sync_attempt(success=False, error=str(exc))
    return conn


def try_sync(conn) -> tuple[bool, str | None]:
    """Sync if the connection supports it. Never raises.

    Returns (ok, error). In local mode: (True, None) — nothing to sync is
    not a failure. Records the outcome in the cache DB for the UI.
    """
    if not isinstance(conn, SyncedConnection):
        return True, None
    try:
        conn.sync()
    except Exception as exc:
        _record_sync_attempt(success=False, error=str(exc))
        return False, str(exc)
    _record_sync_attempt(success=True)
    return True, None


def _record_sync_attempt(success: bool, error: str | None = None) -> None:
    """Persist sync outcome to the cache DB (machine-local, for the UI)."""
    try:
        conn = connect_cache()
        now = str(int(time.time()))
        with conn:
            conn.execute(
                "INSERT INTO kv (key, value) VALUES ('sync:last_attempt_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (now,))
            if success:
                conn.execute(
                    "INSERT INTO kv (key, value) VALUES ('sync:last_ok_at', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (now,))
                conn.execute("DELETE FROM kv WHERE key = 'sync:last_error'")
            elif error is not None:
                conn.execute(
                    "INSERT INTO kv (key, value) VALUES ('sync:last_error', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (error,))
        conn.close()
    except Exception:
        pass  # status bookkeeping must never take the app down


# ---------------------------------------------------------------- cache DB

_cache_init_done = False


def connect_cache() -> sqlite3.Connection:
    """Plain-SQLite, never-synced, per-machine cache store."""
    global _cache_init_done
    conn = sqlite3.connect(cache_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if not _cache_init_done:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        _cache_init_done = True
    return conn


def is_local_only_key(key: str) -> bool:
    return key.startswith(LOCAL_ONLY_KEY_PREFIXES)


# ---------------------------------------------------------------- sync manager

class SyncManager:
    """Owns when sync happens: on demand (debounced after writes) and on a
    background interval. All sync calls hold the app's connection lock so a
    push/pull never interleaves with a write on the shared connection.

    Failures never raise out of here — try_sync records them and the UI
    surfaces them via /sync/status.
    """

    def __init__(self, get_conn, lock, interval: float, debounce: float = 3.0,
                 swap_conn=None):
        import threading
        self._get_conn = get_conn
        self._lock = lock
        self._swap_conn = swap_conn
        self._interval = interval
        self._debounce = debounce
        self._timer: "threading.Timer | None" = None
        self._timer_guard = threading.Lock()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._pending = 0          # writes since last successful sync
        self._threading = threading

    # -- lifecycle

    def start(self) -> None:
        self._thread = self._threading.Thread(
            target=self._loop, name="sync-interval", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._timer_guard:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self.sync_now()  # best-effort final push so a clean quit leaves nothing behind

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.sync_now()

    # -- triggers

    def request_sync(self) -> None:
        """Called after a state write: coalesce bursts, sync soon after."""
        with self._timer_guard:
            self._pending += 1
            if self._timer is not None:
                self._timer.cancel()
            self._timer = self._threading.Timer(self._debounce, self.sync_now)
            self._timer.daemon = True
            self._timer.start()

    def sync_now(self) -> tuple[bool, str | None]:
        try:
            conn = self._get_conn()
        except Exception as exc:
            return False, str(exc)
        with self._lock:
            ok, err = try_sync(conn)
        if not ok and self._swap_conn is not None:
            from . import reconcile
            if reconcile.is_conflict_error(err):
                # Divergence: libSQL refuses to merge, so we do — the
                # documented per-row last-write-wins policy lives there.
                ok, err = reconcile.run(conn, self._lock, self._swap_conn)
        if ok:
            with self._timer_guard:
                self._pending = 0
        return ok, err

    # -- reporting

    def status(self) -> dict:
        st = sync_status_base()
        with self._timer_guard:
            st["pending_changes"] = self._pending
        st["interval_seconds"] = self._interval
        return st


_manager: SyncManager | None = None


def start_sync_manager(get_conn, lock, swap_conn=None) -> None:
    """Called once from the server lifespan. No-op in local mode."""
    global _manager
    if mode() != "synced" or _manager is not None:
        return
    interval = float(_cfg("TURSO_SYNC_INTERVAL", "300"))
    _manager = SyncManager(get_conn, lock, interval, swap_conn=swap_conn)
    _manager.start()


def stop_sync_manager() -> None:
    global _manager
    if _manager is not None:
        _manager.stop()
        _manager = None


def request_sync() -> None:
    """Fire-and-forget: call after any state write. Cheap no-op in local mode."""
    if _manager is not None:
        _manager.request_sync()


def sync_now() -> tuple[bool, str | None]:
    if _manager is None:
        return True, None
    return _manager.sync_now()


def sync_status_base() -> dict:
    """Sync state as stored in the machine-local cache DB."""
    st = {
        "mode": mode(),
        "last_ok_at": None,
        "last_attempt_at": None,
        "last_error": None,
        "last_reconcile_at": None,
    }
    try:
        conn = connect_cache()
        try:
            for key, field in (("sync:last_ok_at", "last_ok_at"),
                               ("sync:last_attempt_at", "last_attempt_at"),
                               ("sync:last_reconcile_at", "last_reconcile_at"),
                               ("sync:last_error", "last_error")):
                row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
                if row:
                    v = row["value"]
                    st[field] = int(v) if field.endswith("_at") else v
        finally:
            conn.close()
    except Exception:
        pass
    return st


def sync_status() -> dict:
    if _manager is not None:
        return _manager.status()
    st = sync_status_base()
    st["pending_changes"] = 0
    st["interval_seconds"] = None
    return st


def migrate_cache_keys(state_conn, lock) -> None:
    """One-time, idempotent: move cache-prefixed kv rows out of the state DB
    into the local cache DB, so they stop syncing. Runs at startup."""
    try:
        with lock:
            rows = state_conn.execute("SELECT key, value FROM kv").fetchall()
        movers = [(r["key"], r["value"]) for r in rows if is_local_only_key(r["key"])]
        if not movers:
            return
        cache = connect_cache()
        with cache:
            cache.executemany(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", movers)
        cache.close()
        with lock:
            for key, _ in movers:
                state_conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            state_conn.commit()
        print(f"[db] moved {len(movers)} cache key(s) to local cache store",
              file=sys.stderr, flush=True)
    except Exception as exc:
        print(f"[db] cache-key migration skipped: {exc}", file=sys.stderr, flush=True)
