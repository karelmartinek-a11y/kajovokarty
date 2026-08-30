from __future__ import annotations

import os
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    data: Path
    database: Path
    logs: Path
    backups: Path
    exports: Path
    diagnostics: Path
    resources: Path
    migrations: Path
    default_data: Path | None = None
    locator_file: Path | None = None


    @property
    def data_dir(self) -> Path:
        return self.data

    @property
    def logs_dir(self) -> Path:
        return self.logs

    @property
    def backups_dir(self) -> Path:
        return self.backups

    @property
    def exports_dir(self) -> Path:
        return self.exports

    @property
    def diagnostics_dir(self) -> Path:
        return self.diagnostics

    @classmethod
    def discover(cls, data_override: Path | None = None) -> "AppPaths":
        if getattr(sys, "frozen", False):
            root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        else:
            root = Path(__file__).resolve().parents[3]
        default_data = Path(user_data_path("KajovoKarty", appauthor=False))
        locator_file = default_data / "data-location.json"
        environment_override = os.environ.get("KAJOVOKARTY_TEST_DATA_DIR")
        if data_override is not None:
            data = data_override
        elif environment_override:
            data = Path(environment_override)
        else:
            data = default_data
            if locator_file.is_file():
                try:
                    payload = json.loads(locator_file.read_text(encoding="utf-8"))
                    configured = str(payload.get("data_directory", "")).strip()
                    if configured:
                        data = Path(configured).expanduser()
                except (OSError, ValueError, TypeError):
                    data = default_data
        return cls(
            root=root,
            data=data,
            database=data / "kajovokarty.sqlite3",
            logs=data / "logs",
            backups=data / "backups",
            exports=data / "exports",
            diagnostics=data / "diagnostics",
            resources=root / "resources",
            migrations=root / "migrations",
            default_data=default_data,
            locator_file=locator_file,
        )

    def ensure(self) -> None:
        if self.default_data is not None:
            self.default_data.mkdir(parents=True, exist_ok=True)
        for path in (self.data, self.logs, self.backups, self.exports, self.diagnostics):
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)

    def set_data_location(self, target: Path) -> None:
        """Atomically select the data directory used on the next start."""
        default_data = self.default_data or self.data
        locator = self.locator_file or (default_data / "data-location.json")
        default_data.mkdir(parents=True, exist_ok=True)
        try:
            is_default = target.resolve() == default_data.resolve()
        except OSError:
            is_default = target.absolute() == default_data.absolute()
        if is_default:
            locator.unlink(missing_ok=True)
            return
        temporary = locator.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"schema_version": 1, "data_directory": str(target.resolve())},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, locator)
