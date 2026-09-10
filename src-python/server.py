"""
Workspace sidecar — FastAPI backend.

Tauri spawns this process on launch and talks to it over localhost. It owns
everything Python: running the rotation fetch, the S/R level detection, and
(later) Ledger persistence. The frontend never runs Python directly — it
calls these endpoints.

Run standalone for development:
    uvicorn server:app --port 8765 --reload

In the packaged app, Tauri starts it via the sidecar mechanism (see
src-tauri/src/main.rs).
"""

from __future__ import annotations

import json
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Local modules — the script logic lifted out of the standalone files.
from engine import rotation, levels, ledger_db, spy, lists_db, luck, fx, alpha

PORT = 8765


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Place for warm-up work later (e.g. opening the SQLite connection).
    print(f"[sidecar] up on :{PORT}", file=sys.stderr, flush=True)
    yield
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
    return lists_db.add_list(req.name)


class ListRename(BaseModel):
    id: str
    name: str


@app.post("/lists/rename")
def lists_rename(req: ListRename):
    return lists_db.rename_list(req.id, req.name)


class ListId(BaseModel):
    id: str


@app.post("/lists/delete")
def lists_delete(req: ListId):
    return lists_db.delete_list(req.id)


class ItemAdd(BaseModel):
    list_id: str
    text: str
    note: str = ""


@app.post("/lists/item/add")
def lists_item_add(req: ItemAdd):
    return lists_db.add_item(req.list_id, req.text, req.note)


class ItemUpdate(BaseModel):
    id: str
    text: str | None = None
    note: str | None = None
    done: bool | None = None


@app.post("/lists/item/update")
def lists_item_update(req: ItemUpdate):
    return lists_db.update_item(req.id, text=req.text, note=req.note, done=req.done)


@app.post("/lists/item/delete")
def lists_item_delete(req: ListId):
    return lists_db.delete_item(req.id)


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
