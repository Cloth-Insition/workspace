# Rollback: back to plain local SQLite with the original data

This procedure returns the app to exactly what it was before the sync
migration — stdlib `sqlite3`, one local `workspace.db`, no Turso — using a
verified backup.

Before reaching for it, note that most problems are smaller than this.
Sync failing is not data loss: see
[SYNC-TROUBLESHOOTING.md](SYNC-TROUBLESHOOTING.md), whose "reset that almost
always works" fixes a broken replica in three steps without giving anything
up. Use this document when you want sync *gone*.

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

To back up what's currently in the *cloud* rather than a local file, point
the script at a synced replica — e.g. the dev one at
`src-python/engine/workspace-synced.db`, after the app has synced it.

## Which copy is the real one?

Since the migration there are several databases. Know which you're
restoring:

| File | What it is |
|---|---|
| `src-python/engine/workspace.db` | Dev, pre-sync plain SQLite. **Untouched fallback copy** — the migration never wrote through it after seeding. |
| `src-python/engine/workspace-synced.db` | Dev, libSQL replica of the cloud. The live one when credentials are set. |
| `%APPDATA%\com.michael.workspace\workspace-synced.db` | Installed app's replica. |
| `%APPDATA%\com.michael.workspace\workspace.db` | Installed app's local-only fallback. Empty unless it has run without credentials. |
| Turso cloud | The shared source of truth while sync is on. |

The current cloud state is the most up-to-date copy. `workspace.db` in the
dev tree is a snapshot from seeding day — fine as a floor, but it does not
contain anything added since.

## Rollback steps

1. **Stop everything.** Close the app window, Ctrl+C the dev terminal. If a
   stray sidecar holds the port: `Get-Process python | Stop-Process -Force`
   (PowerShell). For the installed app, also check Task Manager for
   `workspace-sidecar.exe`.

2. **Capture the current cloud state first** (skip only if you're certain
   you want the older snapshot). With the app synced and closed:

   ```powershell
   cd "C:\Users\mikey\Downloads\Trading Scripts\workspace"
   python scripts\backup_db.py --db src-python\engine\workspace-synced.db
   ```

   That gives you a verified plain-SQLite file containing everything sync
   knew about — use it as the restore source in step 4 if it's newer than
   your last backup.

3. **Check out pre-migration code** (only if you want the old code, not
   just the old storage):

   ```bash
   git switch main
   ```

   `main` holds the pre-migration baseline (`c67d74f` initial commit).
   Once the migration branch is merged, roll back by checking out the tag
   or commit before the merge instead.

   Worth knowing: you usually don't need this. With credentials removed
   (step 5) the current code already behaves exactly like the old code —
   plain `sqlite3`, one local file, no network.

4. **Restore the database.** Delete the live file *and its `-wal`/`-shm`
   siblings* (a stale WAL next to a restored DB corrupts the restore), then
   copy the backup into place:

   ```powershell
   cd src-python\engine
   Remove-Item workspace.db, workspace.db-wal, workspace.db-shm -ErrorAction SilentlyContinue
   Copy-Item ..\..\backups\workspace-<stamp>.db workspace.db
   ```

   For the installed app, the same files live in
   `%APPDATA%\com.michael.workspace\`.

5. **Remove sync credentials** so nothing tries to talk to Turso: delete
   `src-python\.env` for dev, and
   `%APPDATA%\com.michael.workspace\.env` for the installed app (or just
   the two `TURSO_*` lines). Missing credentials on their own already force
   plain-SQLite mode; deleting them is belt and braces.

6. **Optionally leave the migrated schema in place.** The `updated_at`
   columns, triggers and `tombstones` table are harmless without sync —
   nothing reads them. To strip them anyway:

   ```powershell
   python scripts\migrate_002_tombstone_hash.py --down
   python scripts\migrate_001_sync_prep.py --down
   ```

   Both are reversible and tested; the pair restores the exact original
   schema.

7. Relaunch. The app is now running on plain local SQLite with your data
   and no network dependency.

## What rollback does NOT do

- It does not delete or reset the Turso cloud database. If you later resume
  sync against a cloud copy that has diverged, treat the local restored
  file as the source of truth: delete the Turso database in the dashboard,
  create a fresh empty one, and re-seed with
  `scripts/seed_synced_db.py`.
- It does not undo git history — it only moves your checkout. The
  migration branch (`sync-migration`) stays intact for a second attempt.
- It does not uninstall the packaged app. Uninstall via Windows Settings →
  Apps if you want it gone; that leaves `%APPDATA%\com.michael.workspace\`
  and its databases behind, which you can delete by hand once you're sure
  you have a backup.
