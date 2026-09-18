#!/usr/bin/env python3
"""Backup, verify and restore HeatShield's state.

The checklist asks for a *tested* restore, not a backup. Those are different
things: a backup nobody has ever read back is a hope. So this tool has three
verbs, and the test suite exercises the round trip
(`tests/test_backup_restore.py`).

    python scripts/backup.py backup            # snapshot into backups/<stamp>/
    python scripts/backup.py verify backups/…  # checksums vs MANIFEST.json
    python scripts/backup.py restore backups/… # put it back, refusing corruption

What is backed up, and why only this:

  * `data/subscribers.csv` — the only irreplaceable file in the repository. It
    is the opt-in registry; a lost row means somebody stops getting heat
    warnings, and a lost *opt-out* row means somebody who asked to be left
    alone gets texted again.
  * `data/processed/*.csv` — the computed runs and the alert log. Regenerable
    from the forecast, but the alert log is the record of who was warned about
    what, so it is kept.
  * `data/cache/forecast_5d.parquet` — 36 kB, and the reason a fresh clone can
    render a full dashboard with no internet.

What is deliberately not backed up: `data/raw/` (re-downloadable), the frontend
build output (reproducible), and anything under `node_modules` or `.venv`.

The manifest is plain JSON with a sha256 per file, so a restore can prove it is
putting back the bytes that were saved rather than whatever is on the disk now.
Stdlib only: a backup tool that needs pandas to run is a backup tool that fails
on the day it is needed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_DEST = ROOT / "backups"

# Relative to the repository root. Globs are resolved at backup time.
INCLUDE = [
    "data/subscribers.csv",
    "data/processed/risk_daily.csv",
    "data/processed/thermal_daily.csv",
    "data/processed/alert_log.csv",
    "data/cache/forecast_5d.parquet",
]

MANIFEST = "MANIFEST.json"


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=False)
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def backup(dest: Path | None = None) -> Path:
    """Copy the state files into a new timestamped directory with a manifest."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = (dest or DEFAULT_DEST) / stamp
    target.mkdir(parents=True, exist_ok=False)

    files = {}
    for relative in INCLUDE:
        source = ROOT / relative
        if not source.exists():
            # An absent file is recorded as absent, not silently skipped: a
            # restore that quietly drops a file is how people lose data.
            files[relative] = {"present": False}
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        files[relative] = {
            "present": True,
            "sha256": _digest(source),
            "bytes": source.stat().st_size,
        }

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "files": files,
    }
    (target / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"backed up {sum(1 for f in files.values() if f['present'])} file(s) to {target}")
    print(f"  manifest: {target / MANIFEST}")
    return target


def verify(source: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (ok, missing, corrupt) lists of relative paths."""
    manifest = json.loads((source / MANIFEST).read_text(encoding="utf-8"))
    ok: list[str] = []
    missing: list[str] = []
    corrupt: list[str] = []
    for relative, meta in manifest["files"].items():
        if not meta.get("present"):
            continue
        path = source / relative
        if not path.exists():
            missing.append(relative)
        elif _digest(path) != meta["sha256"]:
            corrupt.append(relative)
        else:
            ok.append(relative)
    return ok, missing, corrupt


def restore(source: Path, assume_yes: bool = False) -> int:
    """Verify, then copy the state back into the repository.

    Verification is not optional: restoring a corrupt registry over a good one
    turns a recoverable incident into an unrecoverable one.
    """
    ok, missing, corrupt = verify(source)
    if missing or corrupt:
        print(f"refusing to restore: {len(missing)} missing, {len(corrupt)} corrupt", file=sys.stderr)
        for path in missing:
            print(f"  missing: {path}", file=sys.stderr)
        for path in corrupt:
            print(f"  corrupt: {path}", file=sys.stderr)
        return 2

    print(f"{len(ok)} file(s) verified against the manifest:")
    for relative in ok:
        current = ROOT / relative
        same = current.exists() and _digest(current) == _digest(source / relative)
        print(f"  {'unchanged' if same else 'DIFFERS  '}  {relative}")

    if not assume_yes:
        print("\nre-run with --yes to write these files back over data/")
        return 0

    for relative in ok:
        destination = ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
    print(f"\nrestored {len(ok)} file(s) into {DATA}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    take = sub.add_parser("backup", help="snapshot the state files")
    take.add_argument("--dest", type=Path, default=None, help=f"default: {DEFAULT_DEST}")

    check = sub.add_parser("verify", help="check a snapshot against its manifest")
    check.add_argument("source", type=Path)

    put = sub.add_parser("restore", help="verify, then write a snapshot back")
    put.add_argument("source", type=Path)
    put.add_argument("--yes", action="store_true", help="actually write the files")

    args = parser.parse_args(argv)
    if args.command == "backup":
        backup(args.dest)
        return 0
    if args.command == "verify":
        ok, missing, corrupt = verify(args.source)
        print(f"verified {len(ok)}, missing {len(missing)}, corrupt {len(corrupt)}")
        for path in missing:
            print(f"  missing: {path}")
        for path in corrupt:
            print(f"  corrupt: {path}")
        return 0 if not (missing or corrupt) else 1
    return restore(args.source, assume_yes=args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
