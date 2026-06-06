#!/usr/bin/env python3
"""PFIP disaster-recovery backup (Python).

Implements the nightly backup spec in ``docs/BACKUP.md``:

  * TimescaleDB: ``pg_dump --format=custom`` via ``docker exec pfip-timescaledb``,
    written to a timestamped custom-format dump under ``backups/``.
  * Qdrant: trigger a snapshot per collection via the Qdrant REST API
    (``POST /collections/{c}/snapshots``) and download each snapshot file out
    of the container to the host.
  * ``.env``: GPG-encrypt a copy into the backup set when ``gpg`` is available;
    skipped gracefully otherwise.
  * Retention: prune backup *sets* older than ``--retention-days`` (default 30).
  * Writes a ``manifest.json`` per run plus a line to ``backups/backup.log``.

This is a thin, dependency-light orchestrator: it shells out to the ``docker``
CLI exactly the way ``scripts/backup.ps1`` does (same container names, same
``.env`` handling, same ``backups/`` layout) so the PowerShell and Python paths
stay interchangeable. The only third-party import is ``requests`` for the
Qdrant REST calls, and that is imported lazily so ``--dry-run`` and ``--help``
work with a bare interpreter.

Run it::

    python scripts/backup.py                 # full backup
    python scripts/backup.py --dry-run       # print the plan, touch nothing
    python scripts/backup.py --retention-days 14 --skip-qdrant

Exit codes:
    0  success
    1  environment problem (docker unreachable, container down) before any work
    2  a critical step (pg_dump) failed

The pure helpers near the top (timestamp/filename builders, retention pruning,
manifest construction, the argparse builder) carry no side effects and are unit
-tested in ``backend/tests/test_backup.py`` without touching docker or the net.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# Paths & constants
# --------------------------------------------------------------------------- #

# scripts/backup.py -> repo root is the parent of this file's directory.
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"
DEFAULT_BACKUPS_DIR = ROOT_DIR / "backups"

TIMESCALE_CONTAINER = "pfip-timescaledb"
QDRANT_CONTAINER = "pfip-qdrant"

DEFAULT_RETENTION_DAYS = 30
DB_DUMP_NAME = "timescaledb.dump"  # custom-format pg_dump, matches BACKUP.md §5
ENV_ENC_NAME = ".env.gpg"
MANIFEST_NAME = "manifest.json"
LOG_NAME = "backup.log"

# A backup "set" is a directory named with this stamp format, e.g. 20260606-0100.
STAMP_FORMAT = "%Y%m%d-%H%M"


# --------------------------------------------------------------------------- #
# Pure helpers (no side effects - unit-tested directly)
# --------------------------------------------------------------------------- #


def make_stamp(now: datetime | None = None) -> str:
    """Return a sortable timestamp string for a backup set directory.

    ``20260606-0100``. Naive or aware ``now`` both work; only wall-clock fields
    are used so the result matches local-time scheduling expectations.
    """
    now = now or datetime.now()
    return now.strftime(STAMP_FORMAT)


def parse_stamp(name: str) -> datetime | None:
    """Inverse of :func:`make_stamp`. Returns ``None`` for non-matching names.

    Tolerates a trailing suffix (so ``20260606-0100-monthly`` still parses to
    its date/time) by only looking at the leading ``YYYYMMDD-HHMM``.
    """
    head = name[: len(datetime.now().strftime(STAMP_FORMAT))]
    try:
        return datetime.strptime(head, STAMP_FORMAT)
    except ValueError:
        return None


def backup_set_dir(out_dir: Path, stamp: str) -> Path:
    """Absolute path of the per-run backup set directory."""
    return Path(out_dir) / stamp


@dataclass
class RetentionCandidate:
    """A backup-set directory considered for pruning."""

    path: Path
    when: datetime


def select_for_pruning(
    candidates: Iterable[RetentionCandidate],
    retention_days: int,
    now: datetime | None = None,
) -> list[Path]:
    """Return the paths whose age exceeds ``retention_days``.

    Pure: takes an explicit list of (path, when) and the cutoff. The caller is
    responsible for actually deleting. ``retention_days <= 0`` disables pruning
    (returns an empty list) so an operator can never accidentally wipe history
    by passing 0.
    """
    if retention_days <= 0:
        return []
    now = now or datetime.now()
    cutoff_seconds = retention_days * 86400
    doomed: list[Path] = []
    for c in candidates:
        age = (now - c.when).total_seconds()
        if age > cutoff_seconds:
            doomed.append(c.path)
    return doomed


def discover_backup_sets(out_dir: Path) -> list[RetentionCandidate]:
    """Scan ``out_dir`` for timestamp-named subdirectories.

    Directories whose name does not parse as a stamp are ignored (so an
    operator's ``monthly/`` prefix or stray files are never pruned).
    """
    out = Path(out_dir)
    found: list[RetentionCandidate] = []
    if not out.is_dir():
        return found
    for child in out.iterdir():
        if not child.is_dir():
            continue
        when = parse_stamp(child.name)
        if when is not None:
            found.append(RetentionCandidate(path=child, when=when))
    return found


@dataclass
class Manifest:
    """Structured record of what a single backup run produced."""

    stamp: str
    started_at: str
    root: str
    set_dir: str
    db_dump: str | None = None
    db_bytes: int | None = None
    qdrant_snapshots: list[dict[str, Any]] = field(default_factory=list)
    env_encrypted: str | None = None
    pruned: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False
    ok: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "stamp": self.stamp,
            "started_at": self.started_at,
            "root": self.root,
            "set_dir": self.set_dir,
            "db_dump": self.db_dump,
            "db_bytes": self.db_bytes,
            "qdrant_snapshots": self.qdrant_snapshots,
            "env_encrypted": self.env_encrypted,
            "pruned": self.pruned,
            "warnings": self.warnings,
            "dry_run": self.dry_run,
            "ok": self.ok,
        }


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` file into a dict (comments/blanks ignored).

    Mirrors ``Read-EnvFile`` in ``scripts/_common.ps1`` including the
    strip-surrounding-quotes behaviour, so both code paths read ``.env``
    identically.
    """
    result: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return result
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        eq = line.find("=")
        if eq < 1:
            continue
        key = line[:eq].strip()
        val = line[eq + 1 :].strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        result[key] = val
    return result


def build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser (kept pure so tests can exercise it)."""
    p = argparse.ArgumentParser(
        prog="backup.py",
        description="PFIP disaster-recovery backup (TimescaleDB + Qdrant + .env).",
    )
    p.add_argument(
        "--out-dir",
        default=str(DEFAULT_BACKUPS_DIR),
        help=f"Directory to write backup sets into (default: {DEFAULT_BACKUPS_DIR}).",
    )
    p.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=(
            "Prune backup sets older than N days (default: "
            f"{DEFAULT_RETENTION_DAYS}). 0 disables pruning."
        ),
    )
    p.add_argument(
        "--skip-qdrant",
        action="store_true",
        help="Skip the Qdrant snapshot step.",
    )
    p.add_argument(
        "--skip-env",
        action="store_true",
        help="Skip GPG-encrypting the .env into the backup set.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan and exit without running docker or writing artifacts.",
    )
    return p


# --------------------------------------------------------------------------- #
# Logging (tiny, dependency-free)
# --------------------------------------------------------------------------- #


def _log(level: str, msg: str) -> None:
    print(f"[{level:>4}] {msg}", flush=True)


def info(msg: str) -> None:
    _log("INFO", msg)


def ok(msg: str) -> None:
    _log("OK", msg)


def warn(msg: str) -> None:
    _log("WARN", msg)


def err(msg: str) -> None:
    _log("FAIL", msg)


def append_log(backups_dir: Path, level: str, msg: str) -> None:
    """Append a timestamped line to ``backups/backup.log`` (best-effort)."""
    try:
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        with (backups_dir / LOG_NAME).open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {level} {msg}\n")
    except OSError:
        pass  # logging must never break the backup


# --------------------------------------------------------------------------- #
# Docker / external-tool plumbing (side-effecting)
# --------------------------------------------------------------------------- #


def docker_available() -> bool:
    """True when the docker CLI exists and the daemon answers ``docker info``."""
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def container_running(name: str) -> bool:
    """True when a container by ``name`` exists and is running."""
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return proc.returncode == 0 and proc.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def pg_dump_to(
    dest: Path, pg_user: str, pg_db: str, container: str = TIMESCALE_CONTAINER
) -> int:
    """``docker exec <container> pg_dump -Fc`` streamed to ``dest``.

    Returns the size in bytes of the written dump. Raises ``RuntimeError`` on
    a non-zero exit or a suspiciously tiny file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "docker",
        "exec",
        container,
        "pg_dump",
        "-U",
        pg_user,
        "-d",
        pg_db,
        "-Fc",  # custom format - restorable with pg_restore --clean --if-exists
    ]
    with dest.open("wb") as out_fh:
        proc = subprocess.run(cmd, stdout=out_fh, stderr=subprocess.PIPE, timeout=3600)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"pg_dump exited {proc.returncode}: {stderr}")
    size = dest.stat().st_size
    if size < 100:
        raise RuntimeError(f"pg_dump output suspiciously small ({size} bytes)")
    return size


def gpg_available() -> bool:
    return shutil.which("gpg") is not None


def gpg_encrypt_env(env_file: Path, dest: Path, recipient: str | None) -> None:
    """GPG-encrypt ``env_file`` to ``dest``.

    Uses asymmetric encryption when ``recipient`` (a key id / email) is given,
    otherwise falls back to symmetric (passphrase) mode via ``GPG_PASSPHRASE``
    if that env var is set. Raises ``RuntimeError`` on failure so the caller can
    downgrade it to a warning.
    """
    import os

    dest.parent.mkdir(parents=True, exist_ok=True)
    if recipient:
        cmd = [
            "gpg", "--batch", "--yes", "--encrypt",
            "--recipient", recipient, "--output", str(dest), str(env_file),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    else:
        passphrase = os.environ.get("GPG_PASSPHRASE")
        if not passphrase:
            raise RuntimeError(
                "no GPG recipient and GPG_PASSPHRASE unset - cannot encrypt .env"
            )
        cmd = [
            "gpg", "--batch", "--yes", "--symmetric", "--cipher-algo", "AES256",
            "--passphrase-fd", "0", "--output", str(dest), str(env_file),
        ]
        proc = subprocess.run(
            cmd, input=passphrase, capture_output=True, text=True, timeout=120
        )
    if proc.returncode != 0:
        raise RuntimeError(f"gpg exited {proc.returncode}: {proc.stderr.strip()}")


def qdrant_snapshot(
    base_url: str, dest_dir: Path, container: str = QDRANT_CONTAINER
) -> list[dict[str, Any]]:
    """Trigger + download a Qdrant snapshot for every collection.

    For each collection: ``POST /collections/{c}/snapshots`` then download the
    binary via ``GET /collections/{c}/snapshots/{name}`` to ``dest_dir``.
    Returns a list of ``{collection, snapshot, path, bytes}`` records.

    ``requests`` is imported here so the module loads (and ``--dry-run`` works)
    even when it is not installed.
    """
    import requests  # lazy: keep dry-run / --help dependency-free

    dest_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    resp = requests.get(f"{base_url}/collections", timeout=15)
    resp.raise_for_status()
    collections = [c["name"] for c in resp.json().get("result", {}).get("collections", [])]
    if not collections:
        warn("Qdrant has no collections yet - nothing to snapshot.")
        return records

    for coll in collections:
        snap_resp = requests.post(
            f"{base_url}/collections/{coll}/snapshots", timeout=300
        )
        snap_resp.raise_for_status()
        snap_name = snap_resp.json()["result"]["name"]
        dest = dest_dir / f"{coll}-{snap_name}"
        dl = requests.get(
            f"{base_url}/collections/{coll}/snapshots/{snap_name}",
            timeout=600,
            stream=True,
        )
        dl.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in dl.iter_content(chunk_size=1 << 20):
                if chunk:
                    fh.write(chunk)
        size = dest.stat().st_size
        ok(f"qdrant snapshot: {coll} -> {dest.name} ({size:,} bytes)")
        records.append(
            {
                "collection": coll,
                "snapshot": snap_name,
                "path": str(dest),
                "bytes": size,
            }
        )
    return records


# --------------------------------------------------------------------------- #
# Plan printing (dry-run)
# --------------------------------------------------------------------------- #


def print_plan(args: argparse.Namespace, env: dict[str, str], stamp: str) -> None:
    out_dir = Path(args.out_dir)
    set_dir = backup_set_dir(out_dir, stamp)
    pg_user = env.get("POSTGRES_USER") or "pfip"
    pg_db = env.get("POSTGRES_DB") or "pfip"
    qd_port = env.get("QDRANT_HTTP_PORT") or "6333"

    info("DRY RUN - no docker commands run, no files written.")
    print()
    print(f"  repo root        : {ROOT_DIR}")
    print(f"  backup set dir   : {set_dir}")
    print(f"  retention-days   : {args.retention_days}"
          + ("  (pruning DISABLED)" if args.retention_days <= 0 else ""))
    print()
    print("  Planned steps:")
    print(f"   1. pg_dump -Fc   : docker exec {TIMESCALE_CONTAINER} "
          f"pg_dump -U {pg_user} -d {pg_db} -Fc")
    print(f"                      -> {set_dir / DB_DUMP_NAME}")
    if args.skip_qdrant:
        print("   2. Qdrant        : SKIPPED (--skip-qdrant)")
    else:
        print(f"   2. Qdrant        : POST http://localhost:{qd_port}/collections/"
              "{c}/snapshots per collection")
        print(f"                      -> {set_dir / 'qdrant'}/")
    if args.skip_env:
        print("   3. .env (gpg)    : SKIPPED (--skip-env)")
    elif gpg_available():
        print(f"   3. .env (gpg)    : encrypt {ENV_FILE} -> {set_dir / ENV_ENC_NAME}")
    else:
        print("   3. .env (gpg)    : gpg not installed - would skip gracefully")
    print(f"   4. retention     : prune sets older than {args.retention_days}d in "
          f"{out_dir}")
    print(f"   5. manifest      : write {set_dir / MANIFEST_NAME}")
    print()
    # Surface readiness without failing the dry-run.
    if not docker_available():
        warn("docker is NOT reachable right now - a real run would exit non-zero.")
    else:
        if not container_running(TIMESCALE_CONTAINER):
            warn(f"{TIMESCALE_CONTAINER} is not running - a real run would fail pg_dump.")
        if not args.skip_qdrant and not container_running(QDRANT_CONTAINER):
            warn(f"{QDRANT_CONTAINER} is not running - Qdrant step would be skipped.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    env = read_env_file(ENV_FILE)
    stamp = make_stamp()

    if args.dry_run:
        print_plan(args, env, stamp)
        return 0

    # --- preflight ---------------------------------------------------------
    if not docker_available():
        err("Docker daemon is not reachable. Start Docker Desktop and retry.")
        append_log(out_dir, "ERROR", "docker unreachable; aborting")
        return 1
    if not container_running(TIMESCALE_CONTAINER):
        err(f"{TIMESCALE_CONTAINER} is not running; cannot pg_dump. "
            "Bring the stack up (scripts/up.ps1) and retry.")
        append_log(out_dir, "ERROR", "timescaledb container down; aborting")
        return 1

    set_dir = backup_set_dir(out_dir, stamp)
    set_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(
        stamp=stamp,
        started_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        root=str(ROOT_DIR),
        set_dir=str(set_dir),
    )
    info(f"PFIP backup - {stamp} -> {set_dir}")
    append_log(out_dir, "INFO", f"backup start stamp={stamp}")

    # --- 1) TimescaleDB pg_dump (critical) ---------------------------------
    pg_user = env.get("POSTGRES_USER") or "pfip"
    pg_db = env.get("POSTGRES_DB") or "pfip"
    db_dest = set_dir / DB_DUMP_NAME
    info(f"pg_dump -Fc {pg_db} -> {db_dest}")
    try:
        size = pg_dump_to(db_dest, pg_user, pg_db)
        manifest.db_dump = str(db_dest)
        manifest.db_bytes = size
        ok(f"pg_dump ok ({size:,} bytes)")
        append_log(out_dir, "OK", f"pg_dump wrote {db_dest} ({size} bytes)")
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        err(f"pg_dump failed: {exc}")
        append_log(out_dir, "ERROR", f"pg_dump failed: {exc}")
        _write_manifest(set_dir, manifest)
        return 2  # critical failure

    # --- 2) Qdrant snapshots (best-effort) ---------------------------------
    if args.skip_qdrant:
        info("Qdrant step skipped (--skip-qdrant).")
    elif not container_running(QDRANT_CONTAINER):
        warn(f"{QDRANT_CONTAINER} not running - skipping Qdrant snapshot.")
        manifest.warnings.append("qdrant container not running")
    else:
        qd_port = env.get("QDRANT_HTTP_PORT") or "6333"
        base_url = f"http://localhost:{qd_port}"
        qd_dir = set_dir / "qdrant"
        try:
            manifest.qdrant_snapshots = qdrant_snapshot(base_url, qd_dir)
            append_log(out_dir, "OK",
                       f"qdrant {len(manifest.qdrant_snapshots)} snapshot(s)")
        except Exception as exc:  # noqa: BLE001 - degrade, never fail the run
            warn(f"Qdrant snapshot failed: {exc}")
            manifest.warnings.append(f"qdrant snapshot failed: {exc}")
            append_log(out_dir, "WARN", f"qdrant snapshot failed: {exc}")

    # --- 3) GPG-encrypt .env (best-effort) ---------------------------------
    if args.skip_env:
        info(".env encryption skipped (--skip-env).")
    elif not ENV_FILE.is_file():
        warn(f"{ENV_FILE} not found - skipping .env backup.")
    elif not gpg_available():
        warn("gpg not installed - skipping encrypted .env backup (see BACKUP.md §6).")
        manifest.warnings.append("gpg unavailable; .env not backed up")
    else:
        import os

        env_dest = set_dir / ENV_ENC_NAME
        recipient = os.environ.get("GPG_RECIPIENT")
        try:
            gpg_encrypt_env(ENV_FILE, env_dest, recipient)
            manifest.env_encrypted = str(env_dest)
            ok(f".env encrypted -> {env_dest}")
            append_log(out_dir, "OK", f".env encrypted -> {env_dest}")
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            warn(f".env encryption failed: {exc}")
            manifest.warnings.append(f"gpg encrypt failed: {exc}")
            append_log(out_dir, "WARN", f".env encrypt failed: {exc}")

    # --- 4) Retention ------------------------------------------------------
    candidates = discover_backup_sets(out_dir)
    doomed = select_for_pruning(candidates, args.retention_days)
    # Never prune the set we just created.
    doomed = [p for p in doomed if p.resolve() != set_dir.resolve()]
    for path in doomed:
        try:
            shutil.rmtree(path)
            manifest.pruned.append(str(path))
            info(f"retention: pruned {path.name}")
            append_log(out_dir, "INFO", f"retention pruned {path}")
        except OSError as exc:
            warn(f"retention: could not prune {path}: {exc}")

    # --- 5) Manifest -------------------------------------------------------
    manifest.ok = True
    _write_manifest(set_dir, manifest)
    append_log(out_dir, "OK", f"backup end stamp={stamp}")

    _print_summary(manifest)
    return 0


def _write_manifest(set_dir: Path, manifest: Manifest) -> None:
    try:
        (set_dir / MANIFEST_NAME).write_text(
            json.dumps(manifest.to_dict(), indent=2), encoding="utf-8"
        )
    except OSError as exc:
        warn(f"could not write manifest: {exc}")


def _print_summary(manifest: Manifest) -> None:
    print()
    ok(f"Backup complete - {manifest.stamp}")
    print("  Manifest:")
    print(f"    DB dump        : {manifest.db_dump} ({manifest.db_bytes:,} bytes)"
          if manifest.db_bytes else f"    DB dump        : {manifest.db_dump}")
    if manifest.qdrant_snapshots:
        for s in manifest.qdrant_snapshots:
            print(f"    Qdrant         : {s['collection']} -> {s['path']}")
    else:
        print("    Qdrant         : (none)")
    print(f"    .env encrypted : {manifest.env_encrypted or '(skipped)'}")
    if manifest.pruned:
        print(f"    Pruned         : {len(manifest.pruned)} old set(s)")
    if manifest.warnings:
        print(f"    Warnings       : {len(manifest.warnings)}")
        for w in manifest.warnings:
            print(f"      - {w}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
