from __future__ import annotations

import platform
import sqlite3
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import AppPaths


@dataclass(slots=True)
class PreflightResult:
    passed: bool
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.checks[name] = {"passed": passed, "detail": detail}
        self.passed = self.passed and passed

    def to_json(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": self.checks}


def run_preflight(paths: AppPaths | None = None, *, require_windows: bool = False) -> PreflightResult:
    app_paths = paths or AppPaths.discover()
    result = PreflightResult(True)
    is_64 = struct.calcsize("P") * 8 == 64
    result.add("python_architecture", is_64, f"Python {struct.calcsize('P') * 8}-bit")
    version_ok = sys.version_info[:2] == (3, 11)
    result.add("python_version", version_ok, platform.python_version())
    windows_ok = platform.system() == "Windows"
    result.add("windows_platform", windows_ok or not require_windows, platform.platform())
    try:
        import PySide6

        result.add("pyside6", True, getattr(PySide6, "__version__", "unknown"))
    except Exception as exc:
        result.add("pyside6", False, f"{type(exc).__name__}: {exc}")
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY)")
        conn.close()
        result.add("sqlite", True, sqlite3.sqlite_version)
    except Exception as exc:
        result.add("sqlite", False, f"{type(exc).__name__}: {exc}")
    for label, path in (("resources", app_paths.resources), ("migrations", app_paths.migrations)):
        result.add(label, path.exists() and path.is_dir(), str(path))
    try:
        app_paths.ensure()
        result.add("writable_data", True, str(app_paths.data))
    except Exception as exc:
        result.add("writable_data", False, f"{type(exc).__name__}: {exc}")
    migrations = sorted(app_paths.migrations.glob("[0-9][0-9][0-9]_*.sql"))
    versions = [int(path.name.split("_", 1)[0]) for path in migrations]
    migration_ok = bool(versions) and versions == list(range(1, versions[-1] + 1))
    result.add("migration_files", migration_ok, f"verze {versions}")
    essential = [app_paths.root / "src" / "kajovokarty", app_paths.root / "requirements.lock"]
    missing = [str(path) for path in essential if not path.exists()]
    result.add("repository_integrity", not missing, "OK" if not missing else "Chybí: " + ", ".join(missing))
    return result
