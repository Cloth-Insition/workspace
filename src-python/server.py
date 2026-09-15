"""
Workspace sidecar — FastAPI backend.

Tauri spawns this process on launch and talks to it over localhost. It owns
everything Python: running the rotation fetch, the S/R level detection, and
(later) Ledger persistence. The frontend never runs Python directly — it
calls these endpoints.

Run standalone for development (use the venv — it has libsql):
    .venv/Scripts/python -m uvicorn server:app --port 8765 --reload

In the packaged app, Tauri starts it via the sidecar mechanism (see
src-tauri/src/main.rs).

Sync: with Turso credentials configured (src-python/.env), state replicates
across machines. engine.db owns the how; this file owns the when — sync on
startup (in the connection warm-up), debounced after every state write
(db.request_sync() in the mutating endpoints), and on a background interval
(SyncManager started in the lifespan). /sync/status feeds the UI indicator.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Local modules — the script logic lifted out of the standalone files.
from engine import rotation, levels, ledger_db, spy, lists_db, luck, fx, alpha, db

PORT = 8765


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the state connection off the event loop: in synced mode the first
    # connect performs the startup pull, which needs the network and must not
    # block /health while it runs.
    def warm():
        try:
            ledger_db._connect()
        except Exception as exc:
            print(f"[sidecar] state connection warm-up failed: {exc}",
                  file=sys.stderr, flush=True)
        db.start_sync_manager(ledger_db._connect, ledger_db._lock,
                              swap_conn=ledger_db.swap_connection)
        print(f"[sidecar] db mode: {db.mode()}", file=sys.stderr, flush=True)
    threading.Thread(target=warm, name="db-warmup", daemon=True).start()
    print(f"[sidecar] up on :{PORT}", file=sys.stderr, flush=True)
    yield
    db.stop_sync_manager()
    print("[sidecar] shutting down", file=sys.stderr, flush=True)


app = FastAPI(title="workspace-sidecar", lifespan=lifespan)

# In dev the Vite frontend runs on :1420 (Tauri's default). In the packaged
# app the frontend is served from the Tauri webview origin. Allow both.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Liveness probe the frontend hits on startup to confirm the sidecar is up."""
    return {"ok": True, "service": "workspace-sidecar"}


# ───────────────────────── Sync ─────────────────────────
# State lives on a libSQL synced database when Turso credentials are set
# (see engine/db.py). The UI polls /sync/status; failures are non-fatal and
# the answer must always come back, so this endpoint never raises.

@app.get("/sync/status")
def sync_status():
    """Sync mode and outcome of the last attempts, for the sidebar indicator.

    mode 'local' means no credentials — deliberately not syncing. In mode
    'synced': last_ok_at/last_attempt_at are unix seconds, last_error is the
    message from the most recent failed attempt (cleared on success), and
    pending_changes counts writes since the last successful sync.
    """
    return db.sync_status()


@app.post("/sync/now")
def sync_now():
    """Manual sync trigger (the indicator doubles as a button)."""
    ok, err = db.sync_now()
    return {"ok": ok, "error": err, "status": db.sync_status()}


class RotationRequest(BaseModel):
    # Reserved for later: the frontend will pass the fetch window. For the
    # skeleton the engine uses its own default period.
    period: str | None = None


@app.post("/rotation/scan")
def rotation_scan(req: RotationRequest):
    """Fetch sector ETFs + holdings and return the structured payload, and
    cache it so a tab switch or app restart can reuse it without refetching.

    This is the rotation script's gather() step, returning JSON instead of
    writing an HTML file. The frontend renders the table itself.
    """
    payload = rotation.scan(period=req.period)
    # Cache only a successful fetch (don't poison the cache with an error
    # payload that returned no series).
    if not payload.get("error") and payload.get("fetched"):
        try:
            ledger_db.set_kv("rotation:cache", json.dumps(payload))
            ledger_db.set_kv("rotation:cache_at", str(int(time.time())))
        except Exception:
            pass
    return payload


@app.get("/rotation/cached")
def rotation_cached():
    """Return the last cached scan with its age in seconds, or null if none.

    The frontend uses this on startup: if a recent cache exists it shows
    instantly, and the user can hit refresh for a live fetch when they want
    fresh numbers.
    """
    raw = ledger_db.get_kv("rotation:cache")
    at = ledger_db.get_kv("rotation:cache_at")
    if not raw:
        return {"payload": None, "cached_at": None, "age_seconds": None}
    try:
        payload = json.loads(raw)
    except Exception:
        return {"payload": None, "cached_at": None, "age_seconds": None}
    cached_at = int(at) if at else None
    age = (int(time.time()) - cached_at) if cached_at else None
    return {"payload": payload, "cached_at": cached_at, "age_seconds": age}


class LevelsRequest(BaseModel):
    ticker: str
    lookback: str = "1y"
    min_touches: int = 2
    tolerance: float = 1.0
    span: int = 3


@app.post("/levels/scan")
def levels_scan(req: LevelsRequest):
    """The S/R scanner's --levels mode for one ticker: every qualifying level,
    as structured data, sorted top-down. The frontend renders the ladder.
    """
    return levels.level_map(
        ticker=req.ticker.upper(),
        lookback=req.lookback,
        min_touches=req.min_touches,
        tolerance=req.tolerance,
        span=req.span,
    )


@app.get("/levels/universe")
def levels_universe():
    """The sector→tickers map, so the frontend can offer a sector filter for
    the proximity scan. Reuses the rotation universe (same names)."""
    return {
        "sectors": {
            etf: {"name": rotation.SECTORS[etf], "tickers": rotation.HOLDINGS.get(etf, [])}
            for etf in rotation.HOLDINGS
        }
    }


class ProximityRequest(BaseModel):
    sectors: list[str] | None = None  # None / empty = whole universe
    threshold: float = 2.0
    min_touches: int = 2
    tolerance: float = 1.0
    span: int = 3


@app.post("/levels/proximity")
def levels_proximity(req: ProximityRequest):
    """Universe-wide proximity scan — which names are near a level right now.
    Caches the last result like rotation does, since it's also a slow scan."""
    if req.sectors:
        tickers = []
        for etf in req.sectors:
            tickers.extend(rotation.HOLDINGS.get(etf, []))
    else:
        tickers = [t for names in rotation.HOLDINGS.values() for t in names]
    # De-dupe while preserving order.
    seen = set()
    tickers = [t for t in tickers if not (t in seen or seen.add(t))]

    result = levels.proximity_scan(
        tickers,
        threshold_pct=req.threshold,
        min_touches=req.min_touches,
        tolerance=req.tolerance,
        span=req.span,
    )
    # Cache the full-universe scan (not filtered ones) for instant restart.
    if not req.sectors and result.get("hits") is not None:
        try:
            ledger_db.set_kv("levels:cache", json.dumps(result))
            ledger_db.set_kv("levels:cache_at", str(int(time.time())))
            ledger_db.set_kv("levels:cache_threshold", str(req.threshold))
        except Exception:
            pass
    return result


@app.get("/levels/cached")
def levels_cached():
    """Last cached full-universe proximity scan with age, or null."""
    raw = ledger_db.get_kv("levels:cache")
    at = ledger_db.get_kv("levels:cache_at")
    thr = ledger_db.get_kv("levels:cache_threshold")
    if not raw:
        return {"result": None, "cached_at": None, "age_seconds": None, "threshold": None}
    try:
        result = json.loads(raw)
    except Exception:
        return {"result": None, "cached_at": None, "age_seconds": None, "threshold": None}
    cached_at = int(at) if at else None
    age = (int(time.time()) - cached_at) if cached_at else None
    return {"result": result, "cached_at": cached_at, "age_seconds": age,
            "threshold": float(thr) if thr else None}


# ───────────────────────── Ledger ─────────────────────────
# These mirror the original window.storage surface one-to-one so the frontend's
# load/save functions map directly onto them.

@app.get("/ledger/trades")
def ledger_get_trades():
    """Return the trades array, or {trades: null} if never seeded (lets the
    frontend know to seed its demo data, exactly as before)."""
    return {"trades": ledger_db.load_trades()}


class TradesPayload(BaseModel):
    trades: list[dict]


@app.post("/ledger/trades")
def ledger_save_trades(payload: TradesPayload):
    ledger_db.save_trades(payload.trades)
    db.request_sync()
    return {"ok": True}


class KVGet(BaseModel):
    key: str


class KVSet(BaseModel):
    key: str
    value: str


@app.post("/ledger/kv/get")
def ledger_kv_get(req: KVGet):
    """Generic getter for snapshots, seeded flag, etc."""
    return {"value": ledger_db.get_kv(req.key)}


@app.post("/ledger/kv/set")
def ledger_kv_set(req: KVSet):
    ledger_db.set_kv(req.key, req.value)
    # Cache-prefixed keys live in the local cache DB — nothing to sync.
    if not db.is_local_only_key(req.key):
        db.request_sync()
    return {"ok": True}


class SpyRequest(BaseModel):
    dates: list[str]


@app.post("/ledger/spy")
def ledger_spy(req: SpyRequest):
    """Exact SPY closes for the given dates, via yfinance, cached. Replaces the
    original per-date web-search lookup with official closing prices."""
    return {"prices": spy.spy_prices(req.dates)}


class AlphaRequest(BaseModel):
    trades: list[dict]
    # Override the module default (0.0) to charge a cash rate. See engine/alpha.py.
    risk_free_annual: float | None = None


@app.post("/ledger/alpha")
def ledger_alpha(req: AlphaRequest):
    """Jensen alpha for the ledger: the account return NOT explained by the
    market exposure actually carried.

    Replaces the old frontend `computeAlphaVsSpy`, which was the raw gap
    between the equity curve and a SPY curve — no beta adjustment and no
    account for partial deployment. This needs per-ticker betas, which only the
    sidecar can estimate, so it lives here.
    """
    try:
        return alpha.compute_alpha(
            req.trades,
            risk_free_annual=(
                req.risk_free_annual
                if req.risk_free_annual is not None
                else alpha.RISK_FREE_ANNUAL
            ),
        )
    except alpha.AlphaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ───────────────────────── Lists ─────────────────────────
# Self-contained: renameable lists of want-to-do/done items with optional notes.

@app.get("/lists")
def lists_all():
    return lists_db.get_all()


class ListName(BaseModel):
    name: str


@app.post("/lists/add")
def lists_add(req: ListName):
    result = lists_db.add_list(req.name)
    db.request_sync()
    return result


class ListRename(BaseModel):
    id: str
    name: str


@app.post("/lists/rename")
def lists_rename(req: ListRename):
    result = lists_db.rename_list(req.id, req.name)
    db.request_sync()
    return result


class ListId(BaseModel):
    id: str


@app.post("/lists/delete")
def lists_delete(req: ListId):
    result = lists_db.delete_list(req.id)
    db.request_sync()
    return result


class ItemAdd(BaseModel):
    list_id: str
    text: str
    note: str = ""


@app.post("/lists/item/add")
def lists_item_add(req: ItemAdd):
    result = lists_db.add_item(req.list_id, req.text, req.note)
    db.request_sync()
    return result


class ItemUpdate(BaseModel):
    id: str
    text: str | None = None
    note: str | None = None
    done: bool | None = None


@app.post("/lists/item/update")
def lists_item_update(req: ItemUpdate):
    result = lists_db.update_item(req.id, text=req.text, note=req.note, done=req.done)
    db.request_sync()
    return result


@app.post("/lists/item/delete")
def lists_item_delete(req: ListId):
    result = lists_db.delete_item(req.id)
    db.request_sync()
    return result


# ───────────────────────── Luck Check ─────────────────────────
# Skill-vs-variance scorer. Self-contained: takes trades + per-trade IV typed
# at calc time, beta-adjusts against SPY/QQQ (auto-picked), returns the full
# statistical breakdown. No persistence — pure computation.

class LuckTrade(BaseModel):
    ticker: str
    entryDate: str
    exitDate: str
    entryPrice: float
    exitPrice: float
    iv: float  # decimal, e.g. 0.92 for 92%


class LuckRequest(BaseModel):
    trades: list[LuckTrade]


@app.post("/luck/calculate")
def luck_calculate(req: LuckRequest):
    return luck.calculate([t.model_dump() for t in req.trades])


# ───────────────────────── FX ─────────────────────────
# USD/CHF (CHF=X — francs per dollar, so a falling line means a USD balance
# buys fewer francs). Rate only, no account-value conversion.
#
# No ledger_db caching here: engine.fx keeps its own 15-minute in-memory cache
# keyed on (pair, range, interval), which is what makes clicking through the
# range buttons cheap. An FxError is a genuine failure — surface it as a 502
# rather than returning an empty series the chart would draw as a blank panel.

@app.get("/fx/ranges")
def fx_ranges():
    """Pairs and range buttons the FX tab should offer."""
    return fx.fx_ranges()


class FxRequest(BaseModel):
    pair: str | None = None
    range: str | None = None
    interval: str | None = None


@app.post("/fx/series")
def fx_series(req: FxRequest):
    try:
        return fx.fx_series(
            pair=req.pair or fx.DEFAULT_PAIR,
            range_key=req.range or "6M",
            interval=req.interval,
        )
    except fx.FxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
