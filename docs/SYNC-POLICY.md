# Sync conflict policy

Two machines, one Turso cloud database, each machine on a local libSQL
synced replica (offline writes enabled). This document is the authority on
what happens when they disagree.

## The policy

**Last write wins, per row, decided by `updated_at`** (ISO-8601 UTC; text
order == time order). A deletion is a write too: it leaves a row in
`tombstones` whose `deleted_at` competes on the same timeline. Whatever was
written latest — an edit on either machine, or a deletion — is the version
every machine converges to.

Tie-breaks (identical timestamps, millisecond precision):

* alive beats deleted — never lose data to an equal-time delete
* cloud copy beats local copy — deterministic on both machines

## How it actually runs (important)

libSQL's own sync **does not merge**. Verified empirically 2026-09-10
against Turso: when both replicas have written since they last synced, the
first to push wins and the second gets a permanent server conflict
(`sync error: server returned a conflict`) — it will never sync again on
its own, though it keeps working locally. Transient
`503 … database is locked` responses appear around a conflicted session
and clear in seconds; they are retried, not treated as conflicts.

So the row-level policy above is implemented by the app in
`engine/reconcile.py`, triggered automatically when the sync manager sees
the conflict error:

1. export every syncable row from the stuck replica (under the app lock);
2. move its files aside as a timestamped `.conflict-*` backup (last 3 kept)
   — nothing is destroyed;
3. pull a fresh replica of the cloud;
4. merge the exported rows in, row by row, per the policy above;
5. push (brief retries for the transient 503); a genuinely new conflict —
   the other machine pushed during the merge — simply reconciles again on
   the next sync cycle;
6. swap the fresh connection into the running app.

Any failure before the fresh replica is usable restores the original files
and the app continues on the stuck-but-consistent local copy, shown as
"unsynced" in the sidebar.

## What makes the timestamps trustworthy

* Triggers (migration 001) stamp `updated_at` on every INSERT/UPDATE, so no
  code path can forget it. Explicit `updated_at` values (used by the
  merge itself) override the trigger.
* `save_trades` **diffs** the incoming array against stored rows and only
  writes actual changes — an untouched trade keeps its old `updated_at`, so
  editing trade X on the desktop can never steamroll the laptop's edit of
  trade Y. (Before Phase 5 it rewrote the whole table on every save, which
  would have made every row "just modified" on every save.)
* Writes that change nothing (`set_kv` with the same value, a save with an
  identical array) are skipped entirely — no timestamp churn, no sync
  traffic.

## Deletions and resurrection

Deleting leaves a tombstone `(table_name, row_id, deleted_at,
content_hash)`. Without it, a deleted row would return the next time the
other machine (or a stale UI holding the old array) wrote it back.

The trades bulk-save path has a specific guard: if an incoming trade id
matches a tombstone **and its content hash equals what was deleted**, it is
a stale frontend array resurrecting a dead row — blocked. If the content
differs, it's the user deliberately re-logging a trade under the same
ticker-date id — allowed, and the tombstone is cleared. Lists have no bulk
path (every mutation is per-row), so their tombstones carry no hash.

## Where last-write-wins is imperfect (accepted, eyes open)

* **kv rows are whole-value blobs.** `kv` conflicts resolve per *key*, and
  some keys hold aggregate JSON (notably the Ledger's account-snapshots
  array once it's used). Taking snapshots on BOTH machines inside one
  divergence window means one machine's snapshot blob wins and the other's
  is lost. Judged acceptable for single-user use (snapshots are rare,
  manual). If it ever bites: promote snapshots to a proper table with row
  ids — the machinery here handles the rest.
* **A whole-trade row is the conflict unit.** Editing different *fields* of
  the same trade on both machines resolves to one machine's whole row, not
  a field merge.
* **`seq` (display order) rides along.** Reordering trades or appending on
  both machines can produce duplicate seq values after a merge; the UI
  orders stably and the next save normalises them. Cosmetic.
* **Statistics are unaffected**: they are computed on request from whatever
  trades the machine currently has; they never write state and carry no
  conflict surface.

## Rules learned the hard way

* **Never open the synced database file without its sync credentials.** A
  plain local connection writes changes the replication layer does not
  track: they exist locally, never reach the cloud, and sync happily
  reports OK. (This bit us applying migration 002 — the replica had to be
  rebuilt from the cloud and the migration re-applied through a synced
  connection.) Migration scripts targeting the synced file must go through
  a synced connection, as `scripts/migrate_002_tombstone_hash.py --libsql`
  now does.
* The `.conflict-*` files next to the synced database are pre-reconcile
  backups of a diverged replica. They can be inspected with plain sqlite3
  (read-only!) if a merge ever needs auditing, and are pruned to the last
  three automatically.

## If sync is stuck anyway

The sidebar indicator is the contract: clay "unsynced" that does not clear
within a couple of minutes of being online means reconciliation is failing.
Check the sidecar log for `[reconcile]` lines. The nuclear option that is
always safe: close the app, delete `workspace-synced.db*` (NOT
`workspace.db`), relaunch — the app pulls a fresh replica from the cloud.
Anything the stuck replica alone contained is still in the newest
`.conflict-*` backup. And `docs/ROLLBACK.md` covers abandoning sync
entirely.
