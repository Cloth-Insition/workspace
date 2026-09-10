# Workspace

A local, single-user workspace. A shell with a left sidebar that hosts tools:
the sector-rotation drill-down (sectors → holdings → S/R level ladder), and —
coming next — Ledger and simple lists. Everything runs on your machine. No
server, no subscription, no data leaves the laptop.

## Architecture

```
Tauri shell (Rust)
 ├─ React + Vite frontend  ── the UI, runs in the webview
 └─ Python sidecar (FastAPI) ── spawned on launch, owns all Python
      ├─ /rotation/scan   ← rotation.py fetch logic, returns JSON
      └─ /levels/scan     ← sr_scanner.py pivot/cluster logic, returns JSON
```

The frontend never runs Python. It calls the sidecar over
`http://127.0.0.1:8765`. The detection maths (pivots, clustering, breadth) is
lifted unchanged from your two scripts — only the output changed: structured
JSON instead of a written HTML file, so the UI renders it and you can verify
the raw levels.

## First run

You need three things installed once: Node, Python 3, and the Rust toolchain
(Tauri compiles Rust). Then:

**1. Python sidecar deps**
```bash
cd src-python
python3 -m pip install -r requirements.txt
```

**2. Frontend deps**
```bash
cd ..
npm install
```

**3. Run it**
```bash
npm run tauri dev
```

Tauri spawns the Python sidecar automatically, then opens the window. The
sidebar dot turns steel-cyan once the sidecar's health check passes. Open
Rotation and it fetches live data (takes a minute — it's pulling ~150 tickers
from yfinance with polite spacing, exactly as your script did).

## Testing the sidecar alone

If a tool misbehaves, run the backend by itself to see tracebacks directly:
```bash
cd src-python
python3 -m uvicorn server:app --port 8765 --reload
curl -X POST localhost:8765/levels/scan -H 'Content-Type: application/json' -d '{"ticker":"NVDA"}'
```

## What's built vs. stubbed

- **Built and working:** the shell, sidebar nav, sidecar wiring + health gate,
  the full rotation → holdings → level-ladder drill-down with breadcrumb.
- **Stubbed (placeholders):** Levels (standalone universe scan), Ledger, Lists.
  These are next.

## Packaging later

For a standalone app (no terminal, double-click to launch), the Python sidecar
gets frozen with PyInstaller and bundled as a Tauri sidecar binary, and
`main.rs` switches from `command("python3")` to the bundled binary. Not needed
for daily personal use — `npm run tauri dev` is enough.

## Notes

- Data source is yfinance with no API key, same as the original scripts.
- No IBKR connection runs in the background; the sidecar fetches on demand.
- The design tokens live in `src/styles/tokens.css` — one accent (steel),
  muted up/down, charcoal surfaces. Change the palette there in one place.
```
