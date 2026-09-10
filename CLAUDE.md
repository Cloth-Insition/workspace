# Workspace

Local single-user trading app. Tauri (Rust) shell + React/Vite frontend +
FastAPI Python sidecar on `127.0.0.1:8765`. Data is yfinance, no API key.
No IBKR connection — the sidecar fetches on demand.

## Shared files: read before writing, replace whole

`src-python/server.py`, `src/App.tsx` and `src/lib/api.ts` are touched by
every feature. Previous sessions overwrote them with partial versions and
silently deleted working endpoints — Ledger and Luck Check routes have both
vanished this way. Always read the current file first, then write a complete
replacement. Never a hand-merged delta.

## Running it

Do **not** run `npm run tauri dev` — it's long-running and needs my window.
Ask me to run it and tell you what the terminal prints.

Backend alone is fine for you to run:

    cd src-python
    python -m uvicorn server:app --port 8765 --reload

On Windows the command is `python`, not `python3`.

## Sidecar gotchas

- The sidecar registers routes **only at startup**. After any change to
  `server.py` or `engine/*.py`: close the app window, Ctrl+C the terminal,
  relaunch. A webview reload updates the frontend and leaves the backend
  stale, which looks exactly like "the change didn't apply".
- A 404 on a route that visibly exists in the file means the running sidecar
  is the old one.
- `[Errno 10048]` on bind = stale Python holding the port. Fix in PowerShell:
  `Get-Process python | Stop-Process -Force`
- App starting in ~200ms with a silent terminal = the sidecar never spawned.

## Frontend conventions

- All colour lives in `src/styles/tokens.css`. One accent (steel-cyan), used
  only on the active or selected thing. Up/down are deliberately muted — sea
  green and faded clay, never bright red/green. Charcoal surfaces.
- JetBrains Mono for numbers, Geist for text.
- Each tool has its own plain CSS file at `src/styles/<tool>.css`. Tailwind
  is present for Ledger's layout utilities only — don't convert existing
  components to it.
- recharts is the chart library and is already installed. No new npm
  dependencies without asking.
- `src/lib/api.ts` is the only file that knows the sidecar URL. Every call
  goes through its `post<T>` helper.

## Don't touch

- `vite.config.ts` — the `watch.ignored` entries for `src-tauri` and
  `target` are what stop EBUSY crashes on Windows.
- `src-tauri/tauri.conf.json` shell scope and capabilities.

## Data conventions

yfinance fetches use polite inter-request spacing and retry-with-backoff. An
all-NaN result means rate limiting, not missing data — fail loudly rather
than caching NaNs, which has poisoned the history file before.
