from __future__ import annotations

import json
import platform
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ... import __version__
from ...app.paths import AppPaths
from ..persistence.database import Database
from .logging import redact


class DiagnosticBundleService:
    def __init__(self, paths: AppPaths, database: Database) -> None:
        self.paths = paths
        self.database = database

    def create(self) -> Path:
        self.paths.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = self.paths.diagnostics_dir / f"KajovoKarty-diagnostika-{stamp}.zip"
        status = {
            "version": __version__,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "database_path": str(self.database.path),
            "database_exists": self.database.path.exists(),
            "schema_version": self.database.current_version(),
            "integrity": self._integrity(),
        }
        settings = self._safe_settings()
        runs = self._recent_runs()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("status.json", json.dumps(status, ensure_ascii=False, indent=2))
            archive.writestr("settings.json", json.dumps(settings, ensure_ascii=False, indent=2))
            archive.writestr("recent_runs.json", json.dumps(runs, ensure_ascii=False, indent=2))
            for log in sorted(self.paths.logs_dir.glob("*.jsonl"))[-5:]:
                sanitized = []
                for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        sanitized.append(json.dumps(redact(json.loads(line)), ensure_ascii=False, separators=(",", ":")))
                    except json.JSONDecodeError:
                        sanitized.append(json.dumps({"message": "Neplatný řádek logu byl vynechán."}, ensure_ascii=False))
                archive.writestr(f"logs/{log.name}", "\n".join(sanitized) + "\n")
        return target

    def _integrity(self) -> str:
        try:
            self.database.integrity_check()
            return "ok"
        except Exception as exc:
            return f"failed: {type(exc).__name__}"

    def _safe_settings(self) -> dict[str, Any]:
        if not self.database.path.exists():
            return {}
        rows = self.database.query("SELECT key,typed_value,value_type,updated_at_utc FROM app_setting ORDER BY key")
        return {row["key"]: redact({"value": row["typed_value"], "type": row["value_type"], "updated": row["updated_at_utc"]}) for row in rows}

    def _recent_runs(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if not self.database.path.exists():
            return result
        for table in ("api_sync_run", "booking_import_run", "bank_import_run"):
            try:
                rows = self.database.query(f"SELECT * FROM {table} ORDER BY started_at_utc DESC LIMIT 10")
            except sqlite3.DatabaseError:
                rows = []
            result[table] = [redact(dict(row)) for row in rows]
        return result
