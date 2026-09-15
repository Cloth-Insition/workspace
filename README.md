# Workspace

A local, single-user trading workspace. A shell with a left sidebar that
hosts tools: sector rotation (sectors → holdings → S/R level ladder),
a standalone level scanner, the Ledger, Luck Check, USD/CHF, and Lists.

Everything runs on your machine. Market data is fetched on demand and
analysed locally; no subscription, no server doing the thinking. The one
thing that leaves the machine is your own trade and list state, replicated
between your machines through Turso so the desktop and laptop agree.

## Architecture

```
Tauri shell (Rust)
 ├─ React + Vite frontend  ── the UI, runs in the webview
 └─ Python sidecar (FastAPI) ── spawned on launch, owns all Python
      ├─ /rotation/scan   ← rotation fetch logic, returns JSON
      ├─ /levels/scan     ← pivot/cluster logic, returns JSON
      ├─ /ledger/*        ← trades + key/value state
      ├─ /lists/*         ← lists and items
      ├─ /luck, /ledger/alpha ← statistics, computed locally on request
      └─ /sync/*          ← replication state for the UI indicator
```

The frontend never runs Python. It calls the sidecar over
`http://127.0.0.1:8765`. Statistics, scanning and market-data fetching all
run locally on each machine — only *state* syncs.

### Storage and sync

`engine/db.py` is the only module that knows which driver is in use:

- **With Turso credentials** — state lives in a libSQL synced database with
  offline writes. Reads and writes are local and instant; replication
  happens in the background. The app is fully functional with no network.
- **Without credentials** — plain local SQLite, exactly as before any of
  this existed. No network is ever touched.

Machine-local caches (rotation and level scan results, the SPY price cache)
live in a separate database that never syncs — they're per-machine and
disposable.

Conflicts resolve last-write-wins per row on `updated_at`, with tombstones
so deletions don't resurrect. The mechanism, its consequences, and the
cases where it's imperfect are documented in
[docs/SYNC-POLICY.md](docs/SYNC-POLICY.md).

## Running it in development

You need Node, **Python 3.13** (not 3.14 — the libSQL driver has no 3.14
Windows wheel), and the Rust toolchain.

**1. Python sidecar deps**
```powershell
cd src-python
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**2. Frontend deps**
```powershell
npm install
```

**3. Credentials (optional)**

Create `src-python\.env` with your Turso URL and token to enable sync:

```
TURSO_DATABASE_URL=libsql://...
TURSO_AUTH_TOKEN=...
```

Without it everything still runs, against the local database. The file is
gitignored and must never be committed.

**4. Run it**
```powershell
npm run tauri dev
```

Tauri spawns the sidecar from `.venv` automatically. The sidebar dot turns
steel-cyan once its health check passes.

### Testing the sidecar alone

```powershell
cd src-python
.venv\Scripts\python -m uvicorn server:app --port 8765 --reload
curl -X POST localhost:8765/levels/scan -H "Content-Type: application/json" -d "{\"ticker\":\"NVDA\"}"
```

Use the venv's Python — the system one has no `libsql`.

## Tests

```powershell
cd src-python
.venv\Scripts\python ..\tests\run_all.py            # everything
.venv\Scripts\python ..\tests\run_all.py --offline  # no-network subset
```

Covers migrations (correctness, idempotency, reversibility), the
no-credentials fallback, round-trip replication, offline writes and
reconnection, divergence and conflict resolution, and a statistics
regression check that the same trades produce identical alpha and Luck
Check output before and after the storage migration.

Network tests run against the real Turso database using disposable
`test-*` rows, and verify the cloud is left exactly as they found it.
If a run is interrupted, `tests\clean_test_rows.py` clears the leftovers.

## Building an installer

```powershell
python scripts\make_release.py --version 0.2.0
```

See [docs/RELEASING.md](docs/RELEASING.md) for signing, publishing, and how
the auto-updater works.

## Documentation

| | |
|---|---|
| [SETUP-SECOND-MACHINE.md](docs/SETUP-SECOND-MACHINE.md) | Getting a laptop running from scratch |
| [SYNC-TROUBLESHOOTING.md](docs/SYNC-TROUBLESHOOTING.md) | When sync breaks |
| [SYNC-POLICY.md](docs/SYNC-POLICY.md) | How conflicts resolve, and where the policy is imperfect |
| [ROLLBACK.md](docs/ROLLBACK.md) | Back to plain local SQLite with the original data |
| [RELEASING.md](docs/RELEASING.md) | Building, signing, publishing |

## Backups

The database holds real trade history. Before anything risky:

```powershell
python scripts\backup_db.py
```

It uses SQLite's online backup API (safe while the app is running), then
verifies the copy against the original and refuses to keep an unverified
one. Keep at least one copy somewhere other than this folder.

## Notes

- Data source is yfinance with no API key.
- No IBKR connection runs in the background; the sidecar fetches on demand.
- Design tokens live in `src/styles/tokens.css` — one accent (steel), muted
  up/down, charcoal surfaces. Change the palette there in one place.
