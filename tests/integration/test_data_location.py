from __future__ import annotations

import json
from pathlib import Path

import pytest

from kajovokarty.app.paths import AppPaths
from kajovokarty.application.audit import AuditService
from kajovokarty.application.backup import BackupService
from kajovokarty.application.data_location import DataLocationError, DataLocationService
from kajovokarty.infrastructure.persistence.database import Database
from conftest import insert_invoice


def _paths(root: Path, current: Path, default: Path) -> AppPaths:
    return AppPaths(
        root=root,
        data=current,
        database=current / "kajovokarty.sqlite3",
        logs=current / "logs",
        backups=current / "backups",
        exports=current / "exports",
        diagnostics=current / "diagnostics",
        resources=root / "resources",
        migrations=root / "migrations",
        default_data=default,
        locator_file=default / "data-location.json",
    )


def test_data_location_move_clones_db_tokens_and_writes_atomic_locator(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    current = tmp_path / "current"
    default = tmp_path / "bootstrap"
    paths = _paths(root, current, default)
    paths.ensure()
    database = Database(paths.database, paths.migrations, paths.backups)
    database.migrate()
    insert_invoice(database, "i1", "FA1", 12_345)
    (current / "credentials.dat").write_bytes(b"encrypted-token-container")
    (current / "logs" / "app.log").write_text("log", encoding="utf-8")
    audit = AuditService()
    backup = BackupService(database, paths, audit)
    service = DataLocationService(paths, database, audit, backup)

    target = tmp_path / "new data with spaces"
    result = service.prepare(target)

    assert result == target.resolve()
    copied = Database(target / "kajovokarty.sqlite3", paths.migrations, target / "backups")
    assert copied.scalar("SELECT code FROM invoice WHERE external_id='i1'") == "FA1"
    copied.integrity_check()
    assert (target / "credentials.dat").read_bytes() == b"encrypted-token-container"
    assert (target / "logs" / "app.log").read_text(encoding="utf-8") == "log"
    locator = json.loads((default / "data-location.json").read_text(encoding="utf-8"))
    assert locator["data_directory"] == str(target.resolve())


def test_data_location_rejects_nonempty_target_without_touching_it(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    current = tmp_path / "current"
    default = tmp_path / "bootstrap"
    paths = _paths(root, current, default)
    paths.ensure()
    database = Database(paths.database, paths.migrations, paths.backups)
    database.migrate()
    audit = AuditService()
    service = DataLocationService(paths, database, audit, BackupService(database, paths, audit))
    target = tmp_path / "foreign"
    target.mkdir()
    marker = target / "do-not-touch.txt"
    marker.write_text("foreign", encoding="utf-8")

    with pytest.raises(DataLocationError, match="není prázdná"):
        service.prepare(target)

    assert marker.read_text(encoding="utf-8") == "foreign"
    assert not (default / "data-location.json").exists()
