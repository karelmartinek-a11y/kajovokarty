from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ..app.paths import AppPaths
from ..infrastructure.importers.common import utc_now
from ..infrastructure.persistence.database import Database
from .audit import AuditContext, AuditService
from .settings import SettingsService


class BackupService:
    def __init__(
        self,
        database: Database,
        paths: AppPaths,
        audit: AuditService,
        settings: SettingsService | None = None,
    ) -> None:
        self.database = database
        self.paths = paths
        self.audit = audit
        self.settings = settings

    @property
    def directory(self) -> Path:
        configured = "" if self.settings is None else str(self.settings.get("data.backup_directory") or "").strip()
        return Path(configured).expanduser() if configured else self.paths.backups_dir

    def create(self, reason: str = "Ruční záloha") -> Path:
        backup_directory = self.directory
        backup_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = backup_directory / f"kajovokarty-{stamp}-{uuid4().hex[:8]}.sqlite3"
        self.database.clone_to(target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        self._verify(target)
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            conn.execute("INSERT INTO backup_record(id,file_name,file_path,database_hash,schema_version,reason,created_at_utc,verified_at_utc) VALUES(?,?,?,?,?,?,?,?)", (uuid4().hex, target.name, str(target), digest, self.database.current_version(), reason, utc_now(), utc_now()))
            self.audit.append(conn, event_code="BACKUP_CREATED", operation_label="Vytvořit zálohu", context=AuditContext(correlation), object_ref=f"BACKUP:{target.name}", after={"path": str(target), "hash": digest, "reason": reason})
        return target

    def restore(self, source: Path) -> None:
        self._verify(source)
        safety = self.create("Bezpečnostní kopie před obnovou")
        temporary = self.database.path.with_suffix(".restore.tmp")
        temporary.write_bytes(source.read_bytes())
        self._verify(temporary)
        for suffix in ("-wal", "-shm"):
            Path(str(self.database.path) + suffix).unlink(missing_ok=True)
        temporary.replace(self.database.path)
        for suffix in ("-wal", "-shm"):
            Path(str(self.database.path) + suffix).unlink(missing_ok=True)
        self.database.integrity_check()
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            self.audit.append(conn, event_code="BACKUP_RESTORED", operation_label="Obnovit ze zálohy", context=AuditContext(correlation), object_ref=f"BACKUP:{source.name}", after={"source": str(source), "safety_copy": str(safety)})

    def daily_if_needed(self) -> Path | None:
        today = datetime.now(UTC).date().isoformat()
        latest = self.database.scalar("SELECT created_at_utc FROM backup_record ORDER BY created_at_utc DESC LIMIT 1")
        if latest and str(latest).startswith(today):
            return None
        return self.create("Automatická denní záloha")

    def cleanup(self, retention_days: int) -> int:
        threshold = datetime.now(UTC) - timedelta(days=retention_days)
        removed = 0
        for path in self.directory.glob("*.sqlite3"):
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified < threshold:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    @staticmethod
    def _verify(path: Path) -> None:
        import sqlite3

        if not path.is_file():
            raise ValueError("Záložní soubor neexistuje.")
        conn = sqlite3.connect(path)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise ValueError(f"Záloha nemá platnou integritu: {result}")
        finally:
            conn.close()
