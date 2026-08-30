# Handoff – pouze Windows release gate

## Dosažený stav

Forenzní audit repozitáře proti SSOT 1.1 byl dokončen. Nalezené kódové a dohledávací odchylky byly opraveny; v dostupném prostředí prošlo 121 testů, čtyři migrace, databázová integrita, statický bezpečnostní audit a úplnost registrů. Nezůstává známý implementační blocker. Opraven byl reálně reprodukovaný rozpad `run.bat` způsobený LF-only konci řádků i následná chyba `bootstrap.py: error: the following arguments are required: mode`. Bootstrap nyní deklaruje režimy jako skutečné přepínače a nový soubor `run.bat` zůstává ASCII/CRLF s logem `build\run-bat.log`.
 Opraven byl také reálně pozorovaný problém kontrastu: horní tlačítka už nepřebírají světlé pozadí s bílým textem. Nový theme engine explicitně pokrývá všechny stavy a statický WCAG audit obou témat prošel.

## Přesný Windows postup

Na čistém Windows 10/11 x64 spusťte z kořene repozitáře:

```bat
run.bat --repair
run.bat --check
run.bat --test
.venv\Scripts\python -m ruff check src tests scripts
.venv\Scripts\python -m mypy src
.venv\Scripts\python scripts\ui_contrast_audit.py --root . --output build\ui-contrast-audit.json
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python -m kajovokarty --smoke-test
.venv\Scripts\python scripts\gui_layout_audit.py --output build\gui-audit-100.json --width 1280 --height 720
.venv\Scripts\python scripts\build_release.py
powershell -ExecutionPolicy Bypass -File scripts\installer_smoke.ps1 -Installer "build\release\KajovoKarty-Setup-x64-1.1.0.exe" -Version "1.1.0"
run.bat --check
```

DPI audit zopakujte s `QT_SCALE_FACTOR` 1, 1.25, 1.5, 1.75 a 2. Stejná sekvence je připravena v `.github/workflows/windows-release.yml`.

## Podmínka pro PASS

PASS lze vydat teprve po odstranění všech čtyř položek v `BLOCKERS.json`, úspěšném Windows workflow, smoke testu obou EXE artefaktů a doloženém runtime průchodu blokovaných scénářů.
