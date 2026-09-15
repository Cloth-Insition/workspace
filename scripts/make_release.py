"""
Build a release and prepare (optionally publish) it on GitHub Releases.

The Tauri updater expects a `latest.json` manifest sitting next to the
installer, containing the version, a signature, and the download URL. This
script builds everything, generates that manifest, and — with --publish —
uploads the lot via the GitHub CLI.

Usage, from the repo root:

    python scripts/make_release.py                  # build + manifest only
    python scripts/make_release.py --publish        # also create the release
    python scripts/make_release.py --version 0.2.0  # bump version first

Prerequisites for --publish: `gh auth login` completed, and the repository
existing on GitHub (see docs/RELEASING.md).

Signing: the updater signature requires the private key generated in
Phase 7. Point TAURI_SIGNING_PRIVATE_KEY_PATH at it (default:
~/.tauri/workspace-updater.key). Its content — not the path — is what the
Tauri CLI wants in TAURI_SIGNING_PRIVATE_KEY, which this script handles.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONF = REPO / "src-tauri" / "tauri.conf.json"
CARGO = REPO / "src-tauri" / "Cargo.toml"
PKG = REPO / "package.json"
BUNDLE = REPO / "src-tauri" / "target" / "release" / "bundle" / "nsis"
DEFAULT_KEY = Path.home() / ".tauri" / "workspace-updater.key"


def current_version() -> str:
    return json.loads(CONF.read_text())["version"]


def set_version(v: str) -> None:
    """Keep tauri.conf.json, Cargo.toml and package.json in lockstep."""
    conf = json.loads(CONF.read_text())
    conf["version"] = v
    CONF.write_text(json.dumps(conf, indent=2) + "\n")

    cargo = CARGO.read_text()
    cargo = re.sub(r'^version = "[^"]+"', f'version = "{v}"', cargo, count=1,
                   flags=re.M)
    CARGO.write_text(cargo)

    pkg = json.loads(PKG.read_text())
    pkg["version"] = v
    PKG.write_text(json.dumps(pkg, indent=2) + "\n")
    print(f"version set to {v} in tauri.conf.json, Cargo.toml, package.json")


def repo_slug() -> str:
    """owner/name from the updater endpoint in tauri.conf.json."""
    endpoints = json.loads(CONF.read_text())["plugins"]["updater"]["endpoints"]
    m = re.search(r"github\.com/([^/]+/[^/]+)/releases", endpoints[0])
    if not m:
        raise SystemExit(f"could not parse repo from updater endpoint: {endpoints[0]}")
    return m.group(1)


def build(key_path: Path) -> None:
    if not key_path.exists():
        raise SystemExit(
            f"signing key not found: {key_path}\n"
            "Without it the updater signature cannot be produced. Generate one with:\n"
            "  npm run tauri signer generate -- -w ~/.tauri/workspace-updater.key")

    print("building sidecar…")
    venv_py = REPO / "src-python" / ".venv" / "Scripts" / "python.exe"
    r = subprocess.run([str(venv_py), str(REPO / "scripts" / "build_sidecar.py")],
                       cwd=REPO / "src-python")
    if r.returncode != 0:
        raise SystemExit("sidecar build failed")

    print("building app + installer…")
    env = dict(os.environ)
    env["TAURI_SIGNING_PRIVATE_KEY"] = key_path.read_text().strip()
    env.setdefault("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", "")
    r = subprocess.run(["npm", "run", "tauri", "build"], cwd=REPO, env=env,
                       shell=True)
    if r.returncode != 0:
        raise SystemExit("tauri build failed")


def write_manifest(version: str, notes: str) -> Path:
    setup = BUNDLE / f"Workspace_{version}_x64-setup.exe"
    sig = Path(str(setup) + ".sig")
    if not setup.exists() or not sig.exists():
        raise SystemExit(f"expected artifacts missing:\n  {setup}\n  {sig}")

    slug = repo_slug()
    manifest = {
        "version": version,
        "notes": notes,
        "pub_date": subprocess.run(
            ["git", "log", "-1", "--format=%cI"], cwd=REPO,
            capture_output=True, text=True).stdout.strip(),
        "platforms": {
            "windows-x86_64": {
                "signature": sig.read_text().strip(),
                "url": (f"https://github.com/{slug}/releases/download/"
                        f"v{version}/{setup.name}"),
            }
        },
    }
    out = BUNDLE / "latest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"manifest written: {out}")
    return out


def publish(version: str, notes: str, manifest: Path) -> None:
    setup = BUNDLE / f"Workspace_{version}_x64-setup.exe"
    slug = repo_slug()
    gh = "gh"
    fallback = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "GitHub CLI" / "gh.exe"
    if subprocess.run([gh, "--version"], capture_output=True).returncode != 0:
        if not fallback.exists():
            raise SystemExit("gh CLI not found — install it or publish manually")
        gh = str(fallback)

    tag = f"v{version}"
    print(f"creating release {tag} on {slug}…")
    r = subprocess.run([
        gh, "release", "create", tag,
        str(setup), str(Path(str(setup) + ".sig")), str(manifest),
        "--repo", slug, "--title", f"Workspace {tag}", "--notes", notes,
    ], cwd=REPO)
    if r.returncode != 0:
        raise SystemExit("gh release create failed")
    print(f"published: https://github.com/{slug}/releases/tag/{tag}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="set this version before building")
    ap.add_argument("--notes", default="", help="release notes")
    ap.add_argument("--publish", action="store_true",
                    help="create the GitHub release (needs gh auth)")
    ap.add_argument("--skip-build", action="store_true",
                    help="reuse existing artifacts")
    ap.add_argument("--key", type=Path, default=DEFAULT_KEY)
    args = ap.parse_args()

    if args.version:
        set_version(args.version)
    version = current_version()
    notes = args.notes or f"Workspace {version}"
    print(f"release version: {version}")

    if not args.skip_build:
        build(args.key)
    manifest = write_manifest(version, notes)

    if args.publish:
        publish(version, notes, manifest)
    else:
        print("\nnot published (no --publish). Artifacts ready in:")
        print(f"  {BUNDLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
