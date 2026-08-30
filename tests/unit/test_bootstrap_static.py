from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_run_bat_has_required_modes_and_safe_paths() -> None:
    text = (ROOT / "run.bat").read_text(encoding="utf-8")
    for needle in (
        'cd /d "%~dp0"',
        "chcp 65001",
        "--check",
        "--test",
        "--repair",
        '"%PYTHON_EXE%" "scripts\\bootstrap.py"',
        ".venv\\Scripts\\python.exe",
        "winget install --exact --id Python.Python.3.11",
        "pause",
    ):
        assert needle in text
    assert "ACCESS_TOKEN" not in text
    assert "CLIENT_TOKEN" not in text
    assert "pip install" not in text  # complex installation stays in versioned Python bootstrap


def test_build_contract_and_per_user_installer_are_declared() -> None:
    spec = (ROOT / "build" / "KajovoKarty.spec").read_text(encoding="utf-8")
    installer = (ROOT / "build" / "installer" / "KajovoKarty.iss").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "windows-release.yml").read_text(encoding="utf-8")
    assert "frozen_entry.py" in spec
    assert "KajovoKarty.exe" in installer
    assert "PrivilegesRequired=lowest" in installer
    assert "{localappdata}\\Programs\\KajovoKarty" in installer
    assert "run.bat --check" in workflow
    assert "run.bat --test" in workflow
    assert "build/release/KajovoKarty-Setup-x64-1.1.0.exe" in workflow


def test_bootstrap_verifies_every_locked_distribution_version() -> None:
    source = (ROOT / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    assert "importlib.metadata.version(distribution)" in source
    assert "installed != expected" in source
    assert "pip\", \"check" in source
    assert "requirements.lock obsahuje neuzamčený řádek" in source


def test_run_bat_clears_python_launcher_candidate_before_discovery() -> None:
    text = (ROOT / "run.bat").read_text(encoding="utf-8")
    assert ':find_python\nset "CANDIDATE="' in text.replace("\r\n", "\n")


def test_run_bat_has_cmd_safe_encoding_and_line_endings() -> None:
    raw = (ROOT / "run.bat").read_bytes()
    assert raw.startswith(b"@echo off\r\n")
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in raw.replace(b"\r\n", b"")
    raw.decode("ascii")


def test_run_bat_goto_targets_exist() -> None:
    text = (ROOT / "run.bat").read_text(encoding="ascii")
    labels = {line[1:].strip().lower() for line in text.splitlines() if line.startswith(":")}
    targets: set[str] = set()
    for line in text.splitlines():
        lowered = line.lower()
        marker = "goto :"
        start = 0
        while True:
            index = lowered.find(marker, start)
            if index < 0:
                break
            target = lowered[index + len(marker):].split()[0].strip()
            targets.add(target)
            start = index + len(marker)
    assert targets <= labels
