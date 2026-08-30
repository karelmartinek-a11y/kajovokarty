# KájovoKarty

Lokální desktopová aplikace pro kontrolu dokladů a zdrojů úhrad hotelu podle SSOT 1.1. Technologický základ: Python 3.11.9, PySide6 / Qt 6 Widgets a SQLite.

## Stav tohoto předání

Repozitář prošel přísným forenzním opravným auditem. V dostupném Linux prostředí prošlo 110 testů a nebyla ponechána známá implementační odchylka. Nejde však o finální PASS release: skutečný Windows runtime, Qt/DPI a accessibility audit, ruff/mypy a instalační artefakty nebylo možné poctivě ověřit. Přesný stav je v `RUN_STATUS.json`, `AUDIT_RESULTS.json` a `BLOCKERS.json`.

## Oprava bootstrapu v5

Režimy `--run`, `--check`, `--test` a `--repair` jsou v `scripts/bootstrap.py` definované jako skutečné CLI přepínače. Tím je odstraněna chyba `bootstrap.py: error: the following arguments are required: mode`, která vznikala po úspěšné instalaci Pythonu a vytvoření `.venv`.

## Spuštění

Na podporovaném Windows 10/11 x64 spusťte dvojklikem `run.bat`. Bootstrap vyhledá kompatibilní 64bitový Python 3.11, případně se jej pokusí nainstalovat pro aktuálního uživatele, vytvoří pouze lokální `.venv`, ověří `requirements.lock`, provede preflight a databázové migrace a spustí `python -m kajovokarty`.

`run.bat` je záměrně uložen jako čisté ASCII bez BOM s Windows CRLF konci řádků. Tím se zabrání rozpadu příkazů v `cmd.exe` při spuštění z cesty s mezerami nebo českými znaky. Před bootstrapem zapisuje diagnostiku do `build\run-bat.log`; Python bootstrap pokračuje v `build\bootstrap.log`.

Tokeny Better Hotel nejsou vyžadovány pro otevření aplikace. Zadávají a testují se výhradně v obrazovce **Nastavení**.

## Režimy `run.bat`

```text
run.bat
run.bat --check
run.bat --test
run.bat --repair
```

## Hlavní části

- `src/kajovokarty/` – aplikační zdroje;
- `tests/` – unit, integrační, fixture a GUI smoke testy;
- `migrations/` – verzované SQLite migrace;
- `scripts/` – bootstrap, preflight, audit, GUI audit a release build;
- `docs/SSOT_TRACEABILITY.md` – všech 162 scénářů;
- `docs/OBJECT_ACTION_MATRIX.json` – strojový kontrakt Přílohy B;
- `build/` – PyInstaller/Inno Setup podklady a auditní důkazy.

Pro Windows release gate použijte `docs/BUILD_AND_RELEASE.md` nebo `.github/workflows/windows-release.yml`.
