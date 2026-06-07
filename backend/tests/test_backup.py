"""Pure-logic tests for the disaster-recovery scripts.

These exercise ONLY the side-effect-free helpers in ``scripts/backup.py`` and
``scripts/restore.py``: timestamp/filename builders, retention pruning, the
``.env`` parser, argparse wiring, manifest construction, and backup-set
resolution. No docker, no network, no real deletes — retention is tested
against an explicit candidate list, and set resolution uses ``tmp_path``.

The ``scripts/`` directory isn't on the package path, so we load the modules by
file path via importlib.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"


def _load(mod_name: str, filename: str):
    import sys

    spec = importlib.util.spec_from_file_location(mod_name, _SCRIPTS / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so @dataclass can resolve cls.__module__, and so
    # restore.py's `import backup` finds the already-loaded module.
    sys.modules[mod_name] = mod
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec.loader.exec_module(mod)
    return mod


backup = _load("backup", "backup.py")
restore = _load("restore", "restore.py")


# --------------------------------------------------------------------------- #
# Timestamp / filename helpers
# --------------------------------------------------------------------------- #


def test_make_stamp_format():
    stamp = backup.make_stamp(datetime(2026, 6, 6, 1, 0))
    assert stamp == "20260606-0100"


def test_make_stamp_roundtrips_through_parse():
    when = datetime(2026, 1, 31, 23, 59)
    stamp = backup.make_stamp(when)
    assert backup.parse_stamp(stamp) == when


def test_parse_stamp_rejects_garbage():
    assert backup.parse_stamp("not-a-stamp") is None
    assert backup.parse_stamp("monthly") is None


def test_parse_stamp_tolerates_suffix():
    # An operator-added suffix (e.g. monthly archive) still parses the head.
    assert backup.parse_stamp("20260606-0100-monthly") == datetime(2026, 6, 6, 1, 0)


def test_backup_set_dir():
    out = Path("/tmp/backups")
    assert backup.backup_set_dir(out, "20260606-0100") == out / "20260606-0100"


# --------------------------------------------------------------------------- #
# Retention pruning (pure)
# --------------------------------------------------------------------------- #


def _cand(path: str, days_ago: int, now: datetime) -> "backup.RetentionCandidate":
    return backup.RetentionCandidate(path=Path(path), when=now - timedelta(days=days_ago))


def test_select_for_pruning_basic():
    now = datetime(2026, 6, 6, 1, 0)
    cands = [
        _cand("/b/fresh", 1, now),  # keep
        _cand("/b/edge", 29, now),  # keep (< 30d)
        _cand("/b/old", 31, now),  # prune
        _cand("/b/ancient", 400, now),  # prune
    ]
    doomed = backup.select_for_pruning(cands, retention_days=30, now=now)
    names = {p.name for p in doomed}
    assert names == {"old", "ancient"}


def test_select_for_pruning_zero_disables():
    now = datetime(2026, 6, 6, 1, 0)
    cands = [_cand("/b/ancient", 9999, now)]
    assert backup.select_for_pruning(cands, retention_days=0, now=now) == []


def test_select_for_pruning_negative_disables():
    now = datetime(2026, 6, 6, 1, 0)
    cands = [_cand("/b/ancient", 9999, now)]
    assert backup.select_for_pruning(cands, retention_days=-5, now=now) == []


def test_select_for_pruning_boundary_exactly_n_days_is_kept():
    now = datetime(2026, 6, 6, 1, 0)
    # Exactly 30 days old: age == cutoff, not strictly greater -> kept.
    cands = [_cand("/b/exact", 30, now)]
    assert backup.select_for_pruning(cands, retention_days=30, now=now) == []


def test_select_for_pruning_custom_window():
    now = datetime(2026, 6, 6, 1, 0)
    cands = [_cand("/b/a", 8, now), _cand("/b/b", 6, now)]
    doomed = backup.select_for_pruning(cands, retention_days=7, now=now)
    assert [p.name for p in doomed] == ["a"]


def test_discover_backup_sets_ignores_non_stamp_dirs(tmp_path: Path):
    (tmp_path / "20260606-0100").mkdir()
    (tmp_path / "20260101-0100").mkdir()
    (tmp_path / "monthly").mkdir()  # not a stamp -> ignored
    (tmp_path / "loose.txt").write_text("x")  # file -> ignored
    found = backup.discover_backup_sets(tmp_path)
    names = sorted(c.path.name for c in found)
    assert names == ["20260101-0100", "20260606-0100"]


def test_discover_backup_sets_missing_dir(tmp_path: Path):
    assert backup.discover_backup_sets(tmp_path / "nope") == []


# --------------------------------------------------------------------------- #
# .env parsing
# --------------------------------------------------------------------------- #


def test_read_env_file_basic(tmp_path: Path):
    f = tmp_path / ".env"
    f.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "POSTGRES_USER=pfip",
                'POSTGRES_DB="pfip"',
                "POSTGRES_PASSWORD='secret'",
                "QDRANT_HTTP_PORT=6333",
                "MALFORMED",  # no '=' -> ignored
                "=novalue",  # empty key -> ignored
            ]
        ),
        encoding="utf-8",
    )
    env = backup.read_env_file(f)
    assert env["POSTGRES_USER"] == "pfip"
    assert env["POSTGRES_DB"] == "pfip"  # quotes stripped
    assert env["POSTGRES_PASSWORD"] == "secret"  # single quotes stripped
    assert env["QDRANT_HTTP_PORT"] == "6333"
    assert "MALFORMED" not in env
    assert "" not in env


def test_read_env_file_missing(tmp_path: Path):
    assert backup.read_env_file(tmp_path / "absent") == {}


# --------------------------------------------------------------------------- #
# argparse wiring
# --------------------------------------------------------------------------- #


def test_backup_parser_defaults():
    args = backup.build_parser().parse_args([])
    assert args.retention_days == backup.DEFAULT_RETENTION_DAYS
    assert args.dry_run is False
    assert args.skip_qdrant is False
    assert args.skip_env is False


def test_backup_parser_flags():
    args = backup.build_parser().parse_args(
        ["--retention-days", "14", "--skip-qdrant", "--dry-run", "--out-dir", "/x"]
    )
    assert args.retention_days == 14
    assert args.skip_qdrant is True
    assert args.dry_run is True
    assert args.out_dir == "/x"


def test_restore_parser_requires_from():
    with pytest.raises(SystemExit):
        restore.build_parser().parse_args([])


def test_restore_parser_flags():
    args = restore.build_parser().parse_args(["--from", "latest", "--confirm", "--dry-run"])
    assert args.from_spec == "latest"
    assert args.confirm is True
    assert args.dry_run is True


# --------------------------------------------------------------------------- #
# Manifest construction
# --------------------------------------------------------------------------- #


def test_manifest_to_dict_roundtrip():
    m = backup.Manifest(
        stamp="20260606-0100",
        started_at="2026-06-06T01:00:00+00:00",
        root="/repo",
        set_dir="/repo/backups/20260606-0100",
        db_dump="/repo/backups/20260606-0100/timescaledb.dump",
        db_bytes=12345,
    )
    m.qdrant_snapshots.append({"collection": "kb", "snapshot": "s1", "path": "/x", "bytes": 9})
    m.warnings.append("gpg unavailable")
    d = m.to_dict()
    assert d["stamp"] == "20260606-0100"
    assert d["db_bytes"] == 12345
    assert d["qdrant_snapshots"][0]["collection"] == "kb"
    assert d["ok"] is False
    assert d["warnings"] == ["gpg unavailable"]


# --------------------------------------------------------------------------- #
# Backup-set resolution (restore)
# --------------------------------------------------------------------------- #


def test_resolve_latest(tmp_path: Path):
    old = tmp_path / "20260101-0100"
    new = tmp_path / "20260606-0100"
    old.mkdir()
    new.mkdir()
    assert restore.resolve_backup_set("latest", tmp_path) == new


def test_resolve_by_stamp(tmp_path: Path):
    target = tmp_path / "20260606-0100"
    target.mkdir()
    assert restore.resolve_backup_set("20260606-0100", tmp_path) == target


def test_resolve_by_explicit_path(tmp_path: Path):
    target = tmp_path / "somewhere-else"
    target.mkdir()
    assert restore.resolve_backup_set(str(target), tmp_path) == target


def test_resolve_missing_returns_none(tmp_path: Path):
    assert restore.resolve_backup_set("latest", tmp_path) is None
    assert restore.resolve_backup_set("20260606-0100", tmp_path) is None


def test_describe_set_detects_artifacts(tmp_path: Path):
    s = tmp_path / "20260606-0100"
    s.mkdir()
    (s / backup.DB_DUMP_NAME).write_bytes(b"x" * 200)
    qd = s / "qdrant"
    qd.mkdir()
    (qd / "kb-snap1.snapshot").write_bytes(b"y" * 50)
    desc = restore.describe_set(s)
    assert desc["db_dump"] is not None
    assert len(desc["qdrant_snapshots"]) == 1
    assert desc["qdrant_snapshots"][0].name == "kb-snap1.snapshot"


def test_describe_set_no_db_dump(tmp_path: Path):
    s = tmp_path / "empty"
    s.mkdir()
    desc = restore.describe_set(s)
    assert desc["db_dump"] is None
    assert desc["qdrant_snapshots"] == []
