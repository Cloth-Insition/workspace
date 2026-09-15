# Building and releasing

How a new version gets from the source tree onto both machines.

Two audiences: you on the desktop building it, and the installed app on the
laptop picking it up automatically.

---

## One-time setup

### The signing key

The Tauri updater refuses unsigned updates. The keypair lives **outside the
repository**:

    C:\Users\mikey\.tauri\workspace-updater.key       (private — back this up)
    C:\Users\mikey\.tauri\workspace-updater.key.pub   (public)

The public half is already embedded in `src-tauri/tauri.conf.json`. **Back
up the private key** (password manager, encrypted drive — anywhere but the
repo). If it is lost, installed apps will reject every future update and the
only fix is reinstalling them by hand with a new key.

It was generated with:

```powershell
npm run tauri signer generate -- -w "$env:USERPROFILE\.tauri\workspace-updater.key" --password ""
```

### The GitHub repository

The updater endpoint in `tauri.conf.json` points at:

    https://github.com/Cloth-Insition/workspace/releases/latest/download/latest.json

**The repository must be public** for this to work without embedding a
GitHub token in the app. If you'd rather keep it private, that's fine — but
then auto-update can't work, so remove the `updater` block from
`tauri.conf.json` and distribute installers manually instead.

To create it (after `gh auth login`):

```powershell
gh repo create workspace --public --source . --remote origin --push
```

---

## Cutting a release

From the repo root, with the version you want:

```powershell
python scripts\make_release.py --version 0.2.0 --notes "What changed" --publish
```

That does the whole sequence:

1. writes the version into `tauri.conf.json`, `Cargo.toml` and
   `package.json` (they must agree — the updater compares against the
   running app's version)
2. freezes the Python sidecar with PyInstaller
3. runs `tauri build`, producing the NSIS installer and its `.sig`
4. generates `latest.json` — the manifest the updater fetches
5. creates the GitHub release and uploads installer, signature and manifest

Drop `--publish` to build everything without touching GitHub, and inspect
the artifacts in `src-tauri\target\release\bundle\nsis\` first. Add
`--skip-build` to regenerate the manifest from artifacts you already built.

### Before you release

- Run the tests: `cd src-python; .venv\Scripts\python ..\tests\run_all.py`
- Commit your work — the manifest's `pub_date` comes from the last commit.
- Don't reuse a version number. The updater only offers an update when the
  release version is *higher* than the installed one.

---

## What the laptop sees

On launch, the installed app asks GitHub for `latest.json`, compares its
version against its own, and if there's a newer one shows a dialog:

> Version 0.2.0 is available (you have 0.1.0). Install and restart?

**Install** downloads the installer, verifies its signature against the
embedded public key, installs passively and restarts. **Later** dismisses
it until next launch.

Everything about that check is failure-tolerant: no network, no release yet,
a malformed manifest, or nothing newer all end the same way — silence, and
the app starts normally. The updater never blocks startup.

---

## Manual distribution (no GitHub)

Perfectly reasonable for two machines:

```powershell
python scripts\make_release.py --version 0.2.0
```

Then copy `src-tauri\target\release\bundle\nsis\Workspace_0.2.0_x64-setup.exe`
to the laptop and run it. Installing over an existing version keeps your
data — the database lives in `%APPDATA%\com.michael.workspace\`, which the
installer never touches.

---

## Things that bite

**"A public key has been found, but no private key"** — `tauri build` was
run without the signing key in the environment. `make_release.py` handles
this; if building by hand, note that the Tauri CLI wants the key's
*contents* in `TAURI_SIGNING_PRIVATE_KEY`, and setting only
`TAURI_SIGNING_PRIVATE_KEY_PATH` is not enough.

**SmartScreen warning on install** — expected. The build is unsigned by
design (Windows code signing certificates are an annual cost). **More
info** → **Run anyway**.

**Updater says nothing on a fresh install** — check the release is not a
draft, that `latest.json` is attached as an asset, and that its version is
higher than the installed app's.

**Sidecar changes not appearing** — `make_release.py` rebuilds the frozen
sidecar every time, but a manual `npm run tauri build` does not. Run
`scripts\build_sidecar.py` first when building by hand.
