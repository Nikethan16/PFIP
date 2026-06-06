#!/usr/bin/env python3
"""PFIP disaster-recovery restore (Python).

Counterpart to ``scripts/backup.py``. Restores a backup set produced by that
script back into the *running* PFIP stack:

  * TimescaleDB: ``pg_restore --clean --if-exists --no-owner --no-privileges``
    of the custom-format ``timescaledb.dump`` into ``pfip-timescaledb``.
  * Qdrant: upload each ``qdrant/*.snapshot`` file and recover it via the
    Qdrant REST API (``PUT /collections/{c}/snapshots/upload?priority=snapshot``).

This is DESTRUCTIVE - ``--clean`` drops existing objects before recreating
them. The script therefore refuses to do anything until you either pass
``--confirm`` or answer ``y`` to the interactive prompt (only offered on a
real TTY). ``--dry-run`` lists exactly what *would* be restored and exits 0.

Usage::

    # restore the newest backup set (interactive y/N confirm):
    python scripts/restore.py --from latest

    # restore a specific set by timestamp or path, non-interactive:
    python scripts/restore.py --from 20260606-0100 --confirm

    # see the plan only:
    python scripts/restore.py --from latest --dry-run

The ``--from`` value may be:
  * ``latest``                       - newest timestamped set under --backups-dir
  * a stamp like ``20260606-0100``   - resolved under --backups-dir
  * an absolute/relative directory   - used as-is

Exit codes:
    0  success (or dry-run / user-aborted cleanly)
    1  environment / argument problem (docker down, set not found, not confirmed)
    2  a restore step failed
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

# Reuse the backup module's shared constants & helpers so the two stay in lockstep.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup as _b  # noqa: E402  (intentional: sibling script as a module)

ROOT_DIR = _b.ROOT_DIR
ENV_FILE = _b.ENV_FILE
DEFAULT_BACKUPS_DIR = _b.DEFAULT_BACKUPS_DIR
TIMESCALE_CONTAINER = _b.TIMESCALE_CONTAINER
QDRANT_CONTAINER = _b.QDRANT_CONTAINER
DB_DUMP_NAME = _b.DB_DUMP_NAME

info, ok, warn, err = _b.info, _b.ok, _b.warn, _b.err


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def resolve_backup_set(spec: str, backups_dir: Path) -> Path | None:
    """Resolve a ``--from`` spec to a backup-set directory.

    Returns ``None`` if it cannot be resolved to an existing directory. Pure
    aside from filesystem reads; unit-tested with ``tmp_path``.
    """
    backups_dir = Path(backups_dir)

    if spec == "latest":
        sets = _b.discover_backup_sets(backups_dir)
        if not sets:
            return None
        newest = max(sets, key=lambda c: c.when)
        return newest.path

    # An explicit path (absolute or relative) wins if it exists.
    as_path = Path(spec)
    if as_path.is_dir():
        return as_path

    # Otherwise treat it as a stamp under backups_dir.
    candidate = backups_dir / spec
    if candidate.is_dir():
        return candidate
    return None


def describe_set(set_dir: Path) -> dict[str, Any]:
    """Inspect a backup set and report which artifacts are present (pure read)."""
    set_dir = Path(set_dir)
    db_dump = set_dir / DB_DUMP_NAME
    qd_dir = set_dir / "qdrant"
    snapshots = sorted(qd_dir.glob("*")) if qd_dir.is_dir() else []
    return {
        "set_dir": set_dir,
        "db_dump": db_dump if db_dump.is_file() else None,
        "qdrant_snapshots": [p for p in snapshots if p.is_file()],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="restore.py",
        description="PFIP disaster-recovery restore (DESTRUCTIVE).",
    )
    p.add_argument(
        "--from",
        dest="from_spec",
        required=True,
        help="Backup set: 'latest', a stamp (20260606-0100), or a directory path.",
    )
    p.add_argument(
        "--backups-dir",
        default=str(DEFAULT_BACKUPS_DIR),
        help=f"Where backup sets live (default: {DEFAULT_BACKUPS_DIR}).",
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help="Proceed without the interactive y/N prompt (required when non-interactive).",
    )
    p.add_argument(
        "--skip-qdrant",
        action="store_true",
        help="Restore the DB only; leave Qdrant untouched.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be restored and exit; touch nothing.",
    )
    return p


# --------------------------------------------------------------------------- #
# Side-effecting restore steps
# --------------------------------------------------------------------------- #


def pg_restore_from(
    dump: Path, pg_user: str, pg_db: str, container: str = TIMESCALE_CONTAINER
) -> None:
    """Stream a custom-format dump into ``pg_restore`` inside the container.

    Uses ``--clean --if-exists --no-owner --no-privileges`` so an existing DB is
    overwritten cleanly (and so a fresh DB doesn't choke on missing objects).
    ``pg_restore`` can exit non-zero on benign warnings (e.g. ``--clean`` against
    an empty DB), so we surface a non-zero exit as a WARNING rather than a hard
    failure - the caller verifies row counts separately during a drill.
    """
    cmd = [
        "docker", "exec", "-i", container,
        "pg_restore", "-U", pg_user, "-d", pg_db,
        "--clean", "--if-exists", "--no-owner", "--no-privileges",
    ]
    with dump.open("rb") as in_fh:
        proc = subprocess.run(cmd, stdin=in_fh, stderr=subprocess.PIPE, timeout=3600)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        warn(f"pg_restore exited {proc.returncode} (often benign with --clean): {stderr}")
    else:
        ok("pg_restore completed.")


def qdrant_recover(base_url: str, snapshot_files: list[Path]) -> None:
    """Upload + recover each snapshot file into Qdrant.

    The snapshot files written by ``backup.py`` are named ``<collection>-<snap>``;
    the collection is the part before the first ``-`` of the original name. We
    POST the file to ``PUT /collections/{c}/snapshots/upload``.
    """
    import requests  # lazy import

    for snap in snapshot_files:
        # backup.py names files "<collection>-<snapshotname>".
        collection = snap.name.split("-", 1)[0]
        info(f"qdrant recover: {snap.name} -> collection '{collection}'")
        with snap.open("rb") as fh:
            resp = requests.put(
                f"{base_url}/collections/{collection}/snapshots/upload",
                params={"priority": "snapshot"},
                files={"snapshot": (snap.name, fh)},
                timeout=600,
            )
        resp.raise_for_status()
        ok(f"qdrant recovered '{collection}' from {snap.name}")


# --------------------------------------------------------------------------- #
# Confirmation
# --------------------------------------------------------------------------- #


def confirm_destructive(args: argparse.Namespace) -> bool:
    """Return True only when the operator has authorised a destructive restore."""
    if args.confirm:
        return True
    if not sys.stdin.isatty():
        err("Refusing destructive restore: pass --confirm (no interactive TTY).")
        return False
    resp = input(
        "This OVERWRITES the running TimescaleDB/Qdrant data. Continue? [y/N] "
    ).strip().lower()
    return resp == "y"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def run(args: argparse.Namespace) -> int:
    backups_dir = Path(args.backups_dir)
    set_dir = resolve_backup_set(args.from_spec, backups_dir)
    if set_dir is None:
        err(f"Could not resolve backup set from --from {args.from_spec!r} "
            f"(looked under {backups_dir}).")
        return 1

    desc = describe_set(set_dir)
    info(f"Restore source: {set_dir}")

    if desc["db_dump"] is None:
        err(f"No {DB_DUMP_NAME} in {set_dir}; this is not a valid backup set.")
        return 1

    # --- dry run: list and bail -------------------------------------------
    if args.dry_run:
        info("DRY RUN - nothing will be restored.")
        print()
        print(f"  Would pg_restore : {desc['db_dump']}")
        print(f"                     into {TIMESCALE_CONTAINER} "
              "(--clean --if-exists --no-owner --no-privileges)")
        if args.skip_qdrant:
            print("  Qdrant           : SKIPPED (--skip-qdrant)")
        elif desc["qdrant_snapshots"]:
            for s in desc["qdrant_snapshots"]:
                print(f"  Would recover    : {s.name}")
        else:
            print("  Qdrant           : (no snapshots in set)")
        print()
        if not _b.docker_available():
            warn("docker is NOT reachable right now - a real run would exit non-zero.")
        return 0

    # --- preflight ---------------------------------------------------------
    if not _b.docker_available():
        err("Docker daemon is not reachable. Start Docker Desktop and retry.")
        return 1
    if not _b.container_running(TIMESCALE_CONTAINER):
        err(f"{TIMESCALE_CONTAINER} is not running; cannot pg_restore. "
            "Bring the stack up first.")
        return 1

    if not confirm_destructive(args):
        info("Aborted - no changes made.")
        return 1

    env = _b.read_env_file(ENV_FILE)
    pg_user = env.get("POSTGRES_USER") or "pfip"
    pg_db = env.get("POSTGRES_DB") or "pfip"

    # --- 1) DB restore (critical) -----------------------------------------
    info(f"pg_restore {desc['db_dump']} -> {pg_db}")
    try:
        pg_restore_from(desc["db_dump"], pg_user, pg_db)
    except (OSError, subprocess.SubprocessError) as exc:
        err(f"pg_restore failed: {exc}")
        return 2

    # --- 2) Qdrant restore (best-effort) ----------------------------------
    if args.skip_qdrant:
        info("Qdrant restore skipped (--skip-qdrant).")
    elif not desc["qdrant_snapshots"]:
        info("No Qdrant snapshots in this set - nothing to recover.")
    elif not _b.container_running(QDRANT_CONTAINER):
        warn(f"{QDRANT_CONTAINER} not running - skipping Qdrant recover.")
    else:
        qd_port = env.get("QDRANT_HTTP_PORT") or "6333"
        base_url = f"http://localhost:{qd_port}"
        try:
            qdrant_recover(base_url, desc["qdrant_snapshots"])
        except Exception as exc:  # noqa: BLE001
            warn(f"Qdrant recover failed: {exc}")

    print()
    ok(f"Restore complete from {set_dir}")
    info("Sanity-check row counts, e.g.:")
    info(f"  docker exec -it {TIMESCALE_CONTAINER} psql -U {pg_user} -d {pg_db} "
         "-c \"SELECT symbol, count(*) FROM ohlcv GROUP BY 1 ORDER BY 2 DESC LIMIT 10;\"")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
