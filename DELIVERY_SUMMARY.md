# Delivery summary – forenzně auditovaný BLOCKED repozitář

## Co bylo implementováno a opraveno

Repozitář obsahuje Better Hotel read-only synchronizaci, idempotentní Booking.com a bankovní importy, SQLite migrace, karanténu, přesné minor-unit výpočty, deterministický matching, 1:1 až N:M vazby, skupinové vyrovnání bez falešných alokací, ruční zdroje, source revision alerts, audit a kompenzační undo/redo. PySide6 UI zahrnuje dashboard, párovací plochu se třemi drop cíli, globální vyhledávání, importy, sestavy, audit a nastavení.

Forenzní opravný průchod navíc odstranil chybný Booking SQL dotaz, zpřístupnil všechny technické objekty Přílohy B, doplnil vratné řešení Booking reference, Bill/BillItem refresh, funkční stavové ovladače, opravil dvojité obnovení importu a zavedl strojovou objektově-akční matici. Následné opravné průchody odstranily dvě kritické bootstrap chyby: LF-only `run.bat` byl nahrazen CMD-safe ASCII/CRLF variantou a `scripts/bootstrap.py` nyní přijímá `--run`, `--check`, `--test` a `--repair` jako skutečné argparse přepínače místo neplatných pozičních hodnot.

Kontrastní audit odhalil, že původní globální pravidlo `QWidget` nastavovalo světlé pozadí i tlačítkům, zatímco horní lišta jim nastavovala bílý text bez explicitního pozadí. Barvy jsou nyní centralizované v `src/kajovokarty/ui/theme.py`; normální i vysokokontrastní téma explicitně určují normální, hover, pressed, checked, focus a disabled stavy tlačítek, vstupů, tabulek, menu, záložek, navigace, tooltipů a progresu. Statický WCAG AA audit všech kritických foreground/background párů prošel; minimum je 5,86:1.

## Skutečně spuštěné kontroly

```text
PYTHONPATH=src python -m compileall -q src tests scripts
PYTHONPATH=src pytest -q --cov=src/kajovokarty --cov-report=json:build/coverage-final.json --cov-report=term-missing
PYTHONPATH=src python scripts/forensic_ssot_audit.py --root . --ssot <SSOT.docx> ...
PYTHONPATH=src python scripts/repository_audit.py --blocked-package ...
PYTHONPATH=src python scripts/ui_contrast_audit.py --root . --output build/ui-contrast-audit.json
python -m ruff --version
python -m mypy --version
```

Výsledky: compileall PASS; pytest **121 passed, 2 skipped, 0 failed**; kontrastní audit normálního i vysokokontrastního tématu PASS (minimum 5,86:1); run.bat encoding/label regression PASS; bootstrap CLI mode regression PASS (`tests/unit/test_bootstrap_cli.py`); lokální coverage 41,35 % s nulovým runtime pokrytím PySide6 modulů; migrace 001–004 a SQLite integrity PASS; forenzní audit BLOCKED pouze externími gate. Ruff a mypy nejsou v dostupném balíčkovém zdroji nainstalovatelné.

## Spouštění a build

- uživatelský vstup: `run.bat`;
- modulový entrypoint: `src/kajovokarty/__main__.py`;
- Windows build: `scripts/build_release.py`;
- PyInstaller spec: `build/KajovoKarty.spec`;
- instalátor: `build/installer/KajovoKarty.iss`;
- CI release gate: `.github/workflows/windows-release.yml`.

V tomto balíku nejsou falešné soubory `KajovoKarty.exe` ani `KajovoKarty-Setup-x64-1.1.0.exe`.

## Shoda se SSOT

Dohledávací matice obsahuje všech 162 scénářů: 68 má lokální automatický důkaz, 55 statickou implementační evidenci a 39 vyžaduje Windows/Qt runtime. Známé implementační odchylky po opravách: žádné. Finální stav zůstává BLOCKED, dokud neprojdou čtyři gate v `BLOCKERS.json`.
