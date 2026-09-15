# Setting up a second machine

Two ways in, depending on whether you want to *use* the app on that machine
or *develop* it there.

- **Installed app** — the normal case for the laptop. Ten minutes, no
  toolchain, no Python, no Rust.
- **Development setup** — only if you want to edit code on that machine.

Both end in the same place: the same trades and lists as the desktop, synced
through Turso.

---

## A. Installed app (the laptop)

### 1. Get the installer

From the desktop's build output:

    src-tauri\target\release\bundle\nsis\Workspace_0.1.0_x64-setup.exe

Copy it to the laptop by USB stick, OneDrive, or — once the GitHub
repository exists — download it from the Releases page (see
[RELEASING.md](RELEASING.md)).

### 2. Run the installer

Double-click it. Windows SmartScreen will warn that the publisher is
unknown, because the build is deliberately unsigned (code signing
certificates cost money and this is a personal app). Click **More info** →
**Run anyway**. Install, then launch Workspace from the Start menu.

At this point the app works, but it has no credentials, so it starts in
**local only** mode with an empty database. That is expected. Next step
fixes it.

### 3. Give it the Turso credentials

This is the step that connects the laptop to your data. The app reads
credentials from a file in its own data folder:

    %APPDATA%\com.michael.workspace\.env

Create that file (Notepad is fine, or the PowerShell below) containing the
same two lines as the desktop's `src-python\.env`:

    TURSO_DATABASE_URL=libsql://...
    TURSO_AUTH_TOKEN=...

To copy it from the desktop onto a USB stick (run on the **desktop**):

```powershell
Copy-Item "$env:APPDATA\com.michael.workspace\.env" E:\env-backup.txt
```

And on the **laptop**, with the stick as E:

```powershell
$d = "$env:APPDATA\com.michael.workspace"
New-Item -ItemType Directory -Force $d | Out-Null
Copy-Item E:\env-backup.txt (Join-Path $d ".env")
```

Treat that file like a password — it grants full read/write access to your
trade database. Delete it from the USB stick afterwards.

### 4. Restart the app

Close the window and reopen it. On first launch with credentials it pulls
the whole database from Turso (a few seconds), then:

- your trades and lists appear
- the sidebar indicator at the bottom left reads **synced just now**

That's the laptop done. From now on it syncs on launch, a few seconds after
every change, and every five minutes. Work offline freely — see
[SYNC-POLICY.md](SYNC-POLICY.md) for what happens when both machines change
things while apart.

### A note on the fallback database

If the `.env` file is ever missing or renamed, the app does not fail — it
falls back to a local-only database in that same folder, which on a machine
that has only ever run synced will be **empty**. An empty Ledger with a
"local only" indicator almost always means "credentials not found", not
"data lost". Your data is still in Turso and on the other machine.

---

## B. Development setup (optional)

Only needed if you want to run `npm run tauri dev` and edit code there.

### Prerequisites

- **Git** — https://git-scm.com
- **Node.js** (LTS) — https://nodejs.org
- **Python 3.13** — *not* 3.14: the `libsql` driver has no 3.14 Windows
  wheel. Get it from python.org or `py install 3.13`.
- **Rust toolchain** — https://rustup.rs (Tauri compiles Rust)
- **Visual Studio Build Tools** with the C++ workload, which Rust needs on
  Windows.

### Steps

```powershell
git clone <repository-url> workspace
cd workspace
npm install
```

Create the Python environment (note: **3.13**):

```powershell
cd src-python
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Create `src-python\.env` with the same two `TURSO_*` lines as above. This
is the dev-mode credential location; it is gitignored and must never be
committed.

Run it:

```powershell
npm run tauri dev
```

Tauri spawns the Python sidecar from `.venv` automatically. The sidebar dot
turns steel-cyan once the sidecar's health check passes.

### Dev and installed app on one machine

They are separate installations with separate data:

| | Database location | Credentials |
|---|---|---|
| Dev (`tauri dev`) | `src-python\engine\` | `src-python\.env` |
| Installed app | `%APPDATA%\com.michael.workspace\` | that folder's `.env` |

Both sync to the same Turso database, so they converge anyway — but they
are distinct local replicas, and a change in one appears in the other only
after a sync round trip.

---

## Verifying it all works

A quick end-to-end check across both machines:

1. On the laptop, add a list item (Lists tab) or edit a trade note.
2. Wait a few seconds — the indicator should still read "synced".
3. On the desktop, launch the app (or click the sync indicator to sync now).
4. The change should be there.

If it isn't, see [SYNC-TROUBLESHOOTING.md](SYNC-TROUBLESHOOTING.md).
