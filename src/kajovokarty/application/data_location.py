from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from ..app.paths import AppPaths
from ..infrastructure.importers.common import utc_now
from ..infrastructure.persistence.database import Database
from .audit import AuditContext, AuditService
from .backup import BackupService


class DataLocationError(RuntimeError):
    pass


class DataLocationService:
    """Prepare a consistent data-directory move that takes effect after restart."""

    _COPY_NAMES = (
        "credentials.dat",
        ".credentials.key",
        "logs",
        "backups",
        "exports",
        "diagnostics",
    )

    def __init__(
        self,
        paths: AppPaths,
        database: Database,
        audit: AuditService,
        backup: BackupService,
    ) -> None:
        self.paths = paths
        self.database = database
        self.audit = audit
        self.backup = backup

    def prepare(self, target: Path) -> Path:
        target = target.expanduser().resolve()
        current = self.paths.data.resolve()
        if target == current:
            return target
        if target.exists() and any(target.iterdir()):
            raise DataLocationError(
                "Cílová datová složka není prázdná. Vyberte novou nebo prázdnou složku, "
                "aby nemohlo dojít k přepsání cizích dat."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        probe = target.parent / f".kajovokarty-write-{uuid4().hex}"
        try:
            probe.write_text("ok", encoding="utf-8")
        except OSError as exc:
            raise DataLocationError(f"Do cílového umístění nelze zapisovat: {exc}") from exc
        finally:
            probe.unlink(missing_ok=True)

        safety = self.backup.create("Bezpečnostní záloha před změnou datové složky")
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            self.audit.append(
                conn,
                event_code="DATA_DIRECTORY_RELOCATION_PREPARED",
                operation_label="Změnit datovou složku",
                context=AuditContext(correlation),
                object_ref="SETTING:data.data_directory",
                before={"path": str(current)},
                after={"path": str(target), "safety_backup": str(safety)},
            )

        stage = target.parent / f".{target.name}.kajovokarty-stage-{uuid4().hex}"
        try:
            stage.mkdir(parents=False, exist_ok=False)
            self.database.clone_to(stage / "kajovokarty.sqlite3")
            self._verify_database(stage / "kajovokarty.sqlite3")
            for name in self._COPY_NAMES:
                source = current / name
                destination = stage / name
                if not source.exists():
                    continue
                if source.is_dir():
                    shutil.copytree(source, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, destination)
            for directory in ("logs", "backups", "exports", "diagnostics"):
                (stage / directory).mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.rmdir()
            stage.replace(target)
            self.paths.set_data_location(target)
        except Exception as exc:
            shutil.rmtree(stage, ignore_errors=True)
            raise DataLocationError(
                f"Změna datové složky nebyla dokončena. Původní data zůstala aktivní: {exc}"
            ) from exc
        return target

    @staticmethod
    def _verify_database(path: Path) -> None:
        import sqlite3

        connection = sqlite3.connect(path)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise DataLocationError(f"Kopie databáze neprošla kontrolou integrity: {result}")
        finally:
            connection.close()
