from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "build" / "release"
VERSION = "1.1.0"


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print(">", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def find_iscc() -> Path:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    if found:
        return Path(found)
    raise RuntimeError("Inno Setup 6 Compiler (ISCC.exe) nebyl nalezen.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Produkční EXE a instalátor se musí sestavit na Windows x64.")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    if not args.skip_tests:
        run([sys.executable, "-m", "pytest", "-q", "tests"], env=env)
        run([sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"], env=env)
        run([sys.executable, "-m", "mypy", "src"], env=env)
    RELEASE.mkdir(parents=True, exist_ok=True)
    for path in RELEASE.iterdir():
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    run([
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(RELEASE),
        "--workpath",
        str(ROOT / "build" / "pyinstaller-work"),
        str(ROOT / "build" / "KajovoKarty.spec"),
    ], env=env)
    executable = RELEASE / "KajovoKarty.exe"
    if not executable.is_file():
        raise RuntimeError("PyInstaller nevytvořil KajovoKarty.exe.")
    smoke_env = dict(env)
    smoke_env["KAJOVOKARTY_TEST_DATA_DIR"] = str(ROOT / "build" / "smoke-data")
    run([str(executable), "--smoke-test"], env=smoke_env)
    iscc = find_iscc()
    run([str(iscc), f"/DAppVersion={VERSION}", str(ROOT / "build" / "installer" / "KajovoKarty.iss")])
    installer = RELEASE / f"KajovoKarty-Setup-x64-{VERSION}.exe"
    if not installer.is_file():
        raise RuntimeError("Inno Setup nevytvořil očekávaný instalátor.")
    print(f"PASS: {executable}")
    print(f"PASS: {installer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
