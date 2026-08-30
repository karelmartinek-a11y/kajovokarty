from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import logging
import os
import platform
import sqlite3
import struct
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
LOG = BUILD / "bootstrap.log"
LOCK = ROOT / "requirements.lock"
STATE = Path(sys.prefix) / ".requirements.sha256"
REQUIRED_MODULES = ("PySide6", "httpx", "openpyxl", "xlrd", "dateutil", "platformdirs", "cryptography", "reportlab")


def configure_log() -> logging.Logger:
    BUILD.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("kajovokarty.bootstrap")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(LOG, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(console)
    return logger


def run(command: list[str], logger: logging.Logger, *, env: dict[str, str] | None = None) -> None:
    logger.info("Spouštím: %s", " ".join(command))
    process = subprocess.run(command, cwd=ROOT, env=env, text=True, encoding="utf-8", errors="replace")
    if process.returncode != 0:
        raise RuntimeError(f"Příkaz skončil s kódem {process.returncode}: {' '.join(command)}")


def lock_hash() -> str:
    return hashlib.sha256(LOCK.read_bytes()).hexdigest()


def dependencies_ok() -> bool:
    if not STATE.is_file() or STATE.read_text(encoding="ascii", errors="ignore").strip() != lock_hash():
        return False
    try:
        for module in REQUIRED_MODULES:
            importlib.import_module(module)
        for distribution, expected in locked_distributions().items():
            installed = importlib.metadata.version(distribution)
            if installed != expected:
                return False
    except Exception:
        return False
    result = subprocess.run([sys.executable, "-m", "pip", "check"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def locked_distributions() -> dict[str, str]:
    locked: dict[str, str] = {}
    for raw_line in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirement, _, marker = line.partition(";")
        if marker and "sys_platform" in marker:
            expected_platform = marker.split("==", 1)[1].strip().strip('"\'')
            if sys.platform != expected_platform:
                continue
        name, separator, version = requirement.strip().partition("==")
        if not separator or not name or not version:
            raise RuntimeError(f"requirements.lock obsahuje neuzamčený řádek: {raw_line}")
        locked[name.strip()] = version.strip()
    return locked


def install_dependencies(logger: logging.Logger, *, force: bool) -> None:
    if not force and dependencies_ok():
        logger.info("Uzamčené závislosti odpovídají requirements.lock; instalace se neopakuje.")
        return
    logger.info("Instaluji nebo opravuji uzamčené závislosti pouze do .venv...")
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "pip==25.1.1"], logger)
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--requirement", str(LOCK)], logger)
    run([sys.executable, "-m", "pip", "check"], logger)
    STATE.write_text(lock_hash() + "\n", encoding="ascii")


def preflight(logger: logging.Logger, *, require_windows: bool = True) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    checks["platform"] = platform.platform()
    checks["python"] = platform.python_version()
    checks["architecture_bits"] = struct.calcsize("P") * 8
    checks["python_supported"] = sys.version_info[:2] == (3, 11)
    if platform.system() == "Windows":
        try:
            windows_major = int(sys.getwindowsversion().major)
        except (AttributeError, ValueError):
            windows_major = 0
    else:
        windows_major = 0
    checks["windows_nt_major"] = windows_major
    checks["windows_supported"] = platform.system() == "Windows" and windows_major >= 10
    checks["sqlite_version"] = sqlite3.sqlite_version
    checks["sqlite_fts5"] = sqlite3.connect(":memory:").execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0] == 1
    required_paths = [
        ROOT / "src" / "kajovokarty" / "__main__.py",
        ROOT / "resources",
        *sorted((ROOT / "migrations").glob("[0-9][0-9][0-9]_*.sql")),
        LOCK,
    ]
    checks["files"] = {str(path.relative_to(ROOT)): path.exists() for path in required_paths}
    for folder in (BUILD, ROOT / "resources", ROOT / "migrations"):
        folder.mkdir(parents=True, exist_ok=True)
    probe = BUILD / ".write-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    checks["writeable"] = True
    for module in REQUIRED_MODULES:
        imported = importlib.import_module(module)
        checks[f"import_{module}"] = getattr(imported, "__version__", "ok")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    code = "from kajovokarty.app.paths import AppPaths; from kajovokarty.infrastructure.persistence.database import Database; p=AppPaths.discover(); p.ensure(); d=Database(p.database,p.migrations,p.backups); d.migrate(); d.integrity_check(); print(d.current_version())"
    process = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    checks["database_migration"] = process.returncode == 0
    checks["schema_version"] = process.stdout.strip()
    if process.returncode != 0:
        checks["database_error"] = process.stderr[-2000:]
    failures = []
    if checks["architecture_bits"] != 64:
        failures.append("Python není 64bitový.")
    if not checks["python_supported"]:
        failures.append("Je vyžadován Python 3.11 x64.")
    if require_windows and not checks["windows_supported"]:
        failures.append("Je vyžadován Windows 10/11 x64.")
    if not all(checks["files"].values()):
        failures.append("Chybí povinné soubory repozitáře.")
    if not checks["database_migration"]:
        failures.append("Databázové migrace nebo integrity check selhaly.")
    checks["status"] = "PASS" if not failures else "FAIL"
    checks["failures"] = failures
    (BUILD / "preflight.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info("Preflight: %s", checks["status"])
    if failures:
        raise RuntimeError(" ".join(failures))
    return checks


def build_argument_parser() -> argparse.ArgumentParser:
    """Create a CLI parser whose public modes are real option flags.

    Values beginning with ``--`` cannot be consumed reliably as positional
    arguments by argparse.  ``run.bat`` intentionally calls this script with
    one of these flags, so each mode must be declared as an option.
    """

    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--run", dest="mode", action="store_const", const="--run", help="prepare the environment and start the GUI")
    modes.add_argument("--check", dest="mode", action="store_const", const="--check", help="validate the environment without starting the GUI")
    modes.add_argument("--test", dest="mode", action="store_const", const="--test", help="validate the environment and run automated tests")
    modes.add_argument("--repair", dest="mode", action="store_const", const="--repair", help="recreate and repair the locked environment")
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    logger = configure_log()
    logger.info("KájovoKarty bootstrap %s", datetime.now(UTC).isoformat())
    try:
        install_dependencies(logger, force=args.mode == "--repair")
        preflight(logger, require_windows=True)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        if args.mode == "--test":
            run([sys.executable, "-m", "pytest", "-q", "tests"], logger, env=env)
            return 0
        if args.mode in {"--check", "--repair"}:
            logger.info("Kontrola prostředí byla úspěšná." if args.mode == "--check" else "Virtuální prostředí a uzamčené závislosti byly opraveny.")
            return 0
        process = subprocess.run([sys.executable, "-m", "kajovokarty"], cwd=ROOT, env=env)
        return int(process.returncode)
    except Exception as exc:
        logger.exception("Bootstrap selhal: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
