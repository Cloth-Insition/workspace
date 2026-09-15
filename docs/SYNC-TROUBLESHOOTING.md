# When sync breaks

Start here: **your data is not lost.** Every machine keeps a complete local
copy, and Turso holds another. Sync failing means copies have stopped
talking, not that anything was deleted. Nothing below is urgent — work can
continue on the local copy the whole time.

The sidebar indicator is the contract:

| Indicator | Meaning |
|---|---|
| **synced Xm ago** (green dot) | Healthy. |
| **unsynced · last sync Xm ago** (clay) | Not syncing. Local work is safe; hover for the error. |
| **local only** (grey) | No credentials configured — deliberately not syncing. |
| *nothing shown* | The sidecar isn't answering. See "The app shows no data at all". |

Click the indicator to force a sync attempt at any time.

---

## "unsynced" that clears itself

Normal. Any time the network drops — train, plane, hotel wifi — the app
keeps working locally and reconciles when it reconnects. If it goes green
again within a minute or two of being online, nothing is wrong.

## "unsynced" that stays

Hover the indicator; the tooltip carries the actual error.

**"Host not found" / connection errors** — the machine can't reach Turso.
Check the connection; check the database still exists in the
[Turso dashboard](https://app.turso.tech).

**"401" / "unauthorized"** — the auth token is wrong, revoked, or expired.
Generate a new token in the dashboard and update `.env` on **both** machines
(`%APPDATA%\com.michael.workspace\.env` for the installed app,
`src-python\.env` for dev). Restart the app afterwards — credentials are
read once at startup.

**"conflict"** — both machines changed data while apart. The app handles
this automatically: it merges per-row, newest edit per row wins, and pushes
the result (see [SYNC-POLICY.md](SYNC-POLICY.md)). You may briefly see
"unsynced" while it happens. If it *stays* stuck on a conflict for more than
a few minutes, use the reset below.

**Anything else** — read the sidecar log. In dev it's the terminal running
`npm run tauri dev`, and lines starting `[reconcile]` or `[db]` are the
relevant ones.

## The reset that almost always works

Safe because it throws away only the local *replica*, never the source of
truth — your data lives in Turso and on the other machine.

1. Close the app completely.
2. Delete the synced replica files (keep `workspace.db` — that's the
   pre-sync fallback copy):

   ```powershell
   Remove-Item "$env:APPDATA\com.michael.workspace\workspace-synced.db*"
   ```

   For a dev checkout, the same files live in `src-python\engine\`.

3. Relaunch. The app pulls a fresh replica from Turso.

Anything that existed *only* on that machine and had never synced is
preserved in a `.conflict-*` backup file next to the database — see below.

## The app shows no data at all

Almost always missing credentials rather than lost data. Check the
indicator: **local only** means the app never found a `.env`, so it started
an empty local database. Confirm the file exists at
`%APPDATA%\com.michael.workspace\.env` with both `TURSO_*` lines, then
restart. [SETUP-SECOND-MACHINE.md](SETUP-SECOND-MACHINE.md) has the exact
contents.

If the indicator shows nothing at all, the sidecar isn't running. In dev, a
stale Python process holding port 8765 is the usual cause:

```powershell
Get-Process python | Stop-Process -Force
```

Then relaunch.

## Recovering data from a `.conflict-*` backup

When the app rebuilds a diverged replica it first sets the old one aside as
`workspace-synced.db.conflict-<timestamp>` (the last three are kept). These
are ordinary SQLite files. To look inside one without disturbing anything:

```powershell
cd "C:\Users\mikey\Downloads\Trading Scripts\workspace"
python -c "import sqlite3; c=sqlite3.connect('file:PATH_TO_FILE?mode=ro', uri=True); print(c.execute('SELECT COUNT(*) FROM trades').fetchone())"
```

In practice you should never need these — the merge preserves the newest
version of every row automatically. They exist so that a merge can be
audited rather than trusted.

## Starting over completely

If the cloud database itself gets into a state you don't trust, the desktop
can rebuild it from scratch:

1. Back up first: `python scripts\backup_db.py`
2. Delete the database in the Turso dashboard and create a new empty one.
3. Put the new URL and token in `src-python\.env`.
4. Delete the local synced replica (`src-python\engine\workspace-synced.db*`).
5. Re-seed from the plain local database:

   ```powershell
   cd src-python
   .venv\Scripts\python ..\scripts\seed_synced_db.py
   ```

   It verifies the upload by pulling an independent replica and comparing
   content, and refuses to run against a non-empty cloud database.

6. On the laptop: new credentials in its `.env`, delete its synced replica,
   relaunch.

## Abandoning sync entirely

[ROLLBACK.md](ROLLBACK.md) — back to plain local SQLite with the original
data, no Turso involved.

## Checking the cloud directly

To see what Turso actually holds, independent of any local copy:

```powershell
cd src-python
.venv\Scripts\python -c "import os,tempfile,libsql; from engine import db; db._load_env(); d=tempfile.mkdtemp(); c=libsql.connect(d+'/v.db', sync_url=os.environ['TURSO_DATABASE_URL'], auth_token=os.environ['TURSO_AUTH_TOKEN'], offline=True); c.sync(); print('trades in cloud:', c.execute('SELECT COUNT(*) FROM trades').fetchone()[0])"
```

That pulls a throwaway replica into a temp folder and touches nothing else.
