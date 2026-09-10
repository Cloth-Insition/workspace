# Rollback: back to plain local SQLite with the original data

This procedure returns the app to exactly what it was before the sync
migration — stdlib `sqlite3`, one local `workspace.db`, no Turso — using a
verified backup. It works from any later phase, whether or not the libSQL
driver swap has happened yet.

## Where backups are

`backups/` in the repo root (gitignored). One file per backup:
`workspace-YYYYMMDD-HHMMSS.db`. The `.db` file alone is the complete
backup — any `-wal`/`-shm` files next to it are empty artifacts and not
needed.

Take a new backup at any time (safe while the app is running):

```bash
python scripts/backup_db.py
```

The script verifies the copy (integrity check + full content comparison
against the live DB) and refuses to keep an unverified backup. To re-verify
an existing backup later:

```bash
python scripts/backup_db.py --verify-only backups/workspace-<stamp>.db
```

**Keep at least one backup somewhere outside this folder** (another drive
or cloud storage). A backup that lives only next to the thing it protects
is half a backup.

## Rollback steps

1. **Stop everything.** Close the app window, Ctrl+C the dev terminal. If
   a stray sidecar holds the port: `Get-Process python | Stop-Process -Force`
   (PowerShell).

2. **Check out pre-migration code** (only needed if the driver swap phase
   has landed on your current branch):

   ```bash
   git switch main
   ```

   `main` holds the pre-migration baseline (`c67d74f` initial commit).
   Later, once migration phases merge to main, roll back by checking out
   the tag/commit before the merge instead.

3. **Restore the database.** The live DB is
   `src-python/engine/workspace.db`. Delete the live file *and its
   `-wal`/`-shm` siblings* (a stale WAL next to a restored DB corrupts the
   restore), then copy the backup into place:

   ```powershell
   cd src-python\engine
   Remove-Item workspace.db, workspace.db-wal, workspace.db-shm -ErrorAction SilentlyContinue
   Copy-Item ..\..\backups\workspace-<stamp>.db workspace.db
   ```

4. **Verify before trusting it:**

   ```bash
   python scripts/backup_db.py --verify-only src-python/engine/workspace.db
   ```

   (Compares the restored file against itself structurally: integrity
   check + row counts. Counts as of the 2026-09-10 baseline backup:
   trades 40, kv 8, lists 1, list_items 2.)

5. **Remove sync credentials** so nothing tries to talk to Turso: delete
   `src-python/.env` (or just the two `TURSO_*` lines). After the Phase 3
   driver swap, missing credentials on their own already force plain-SQLite
   mode; deleting them is belt and braces.

6. Relaunch. The app is now running pre-migration code on the restored
   pre-migration data.

## What rollback does NOT do

- It does not delete or reset the Turso cloud database. If a later attempt
  resumes sync against a cloud copy that has diverged, treat the local
  restored file as the source of truth: delete the Turso database in the
  dashboard and re-create it empty before re-running the migration.
- It does not undo git history — it only moves your checkout. The
  migration branch (`sync-migration`) stays intact for a second attempt.
