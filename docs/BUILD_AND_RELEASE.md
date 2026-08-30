# Build a release

## Požadavky

- čistý Windows 10/11 x64;
- Python 3.11.9 x64;
- přístup k balíčkovému zdroji pro všechny verze v `requirements.lock`;
- Inno Setup 6;
- běžný účet uživatele; administrátorská práva nejsou požadována pro provoz ani per-user instalaci.

## Povinná validační sekvence

```bat
run.bat --repair
run.bat --check
run.bat --test
.venv\Scripts\python -m ruff check src tests scripts
.venv\Scripts\python -m mypy src
set QT_QPA_PLATFORM=offscreen
set KAJOVOKARTY_TEST_DATA_DIR=%TEMP%\kajovokarty-smoke
.venv\Scripts\python -m kajovokarty --smoke-test
```

DPI audit proveďte pro `QT_SCALE_FACTOR` 1, 1.25, 1.5, 1.75 a 2:

```bat
.venv\Scripts\python scripts\gui_layout_audit.py --output build\gui-audit.json --width 1280 --height 720
```

Poté sestavte release:

```bat
.venv\Scripts\python scripts\build_release.py
powershell -ExecutionPolicy Bypass -File scripts\installer_smoke.ps1 -Installer "build\release\KajovoKarty-Setup-x64-1.1.0.exe" -Version "1.1.0"
run.bat --check
```

## Očekávané artefakty

- `build/release/KajovoKarty.exe`;
- `build/release/KajovoKarty-Setup-x64-1.1.0.exe`.

Instalátor je per-user, zachovává `%LOCALAPPDATA%\KajovoKarty` při běžné odinstalaci a obsahuje licenci, README a uživatelskou příručku.

## Automatizace

Stejný release gate je deklarován v `.github/workflows/windows-release.yml`. Artefakty nejsou v tomto BLOCKED balíku přiloženy, protože je nelze korektně vytvořit na Linuxu a nebyl dostupný připojený Windows runner.
