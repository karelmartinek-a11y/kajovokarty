# Forenzní audit KájovoKarty proti SSOT 1.1

**Verdikt: BLOCKED**

SSOT SHA-256: `cc8cde98cb8c7be0fd3869ab6e1ac03bf14b89a56d8b9e34c680bc75e62983d5`

| ID | Oblast | Stav | Zjištění |
|---|---|---|---|
| SSOT-IDENTITY | SSOT | PASS | Autoritativní SSOT 1.1 byl načten a identifikován. |
| SSOT-ACCEPTANCE-CARDINALITY | SSOT | PASS | SSOT=162, manifest=162, očekáváno=162 |
| SSOT-ACTION-CARDINALITY | SSOT | PASS | 38 akcí; chybějící v DOCX: [] |
| SSOT-UI-CARDINALITY | SSOT | PASS | 76 UI komponent; chybějící v DOCX: [] |
| UI-ACTION-REGISTRY | UI | PASS | enum=38, specs=38, přesné odchylky=[] |
| UI-ACTION-HANDLERS | UI | PASS | Akce bez dohledatelného handleru: [] |
| UI-OBJECT-ACTION-MATRIX | UI | PASS | Objekty=15, chybějící vazby=[] |
| UI-COMPONENT-REGISTRY | UI | PASS | enum=76, specs=76, přesné odchylky=[] |
| UI-COMPONENT-LIVE-BINDINGS | UI | PASS | Komponenty bez dohledatelné živé vazby: [] |
| REPO-TREE | Repository | PASS | Chybí: [] |
| REPO-SECRETS | Security | PASS | Nálezy: [] |
| REPO-PLACEHOLDERS | Repository | PASS | Nálezy: [] |
| REPO-NO-INPUTS | Security | PASS | Nálezy: [] |
| PY-AST | Static | PASS | Chyby: [] |
| MONEY-NO-FLOAT | Finance | PASS | Nálezy: [] |
| API-READ-ONLY | API | PASS | forbidden=[], endpoint=True, headers=True |
| DB-MIGRATIONS | Database | PASS | migrace=[1, 2, 3, 4], integrity=ok, foreign_key_errors=0 |
| BOOTSTRAP-STATIC | Build | PASS | ASCII bez BOM, výhradně CRLF. |
| BUILD-REPRODUCIBLE-STATIC | Build | PASS | Chybí: [] |
| WINDOWS-RUN-BAT | Runtime | BLOCKED | Host=Linux x86_64; skutečný Windows CMD nebyl dostupný. |
| QT-GUI-DPI | UI runtime | BLOCKED | PySide6 runtime není dostupný: No module named 'PySide6' |
| WINDOWS-EXE-INSTALLER | Build | BLOCKED | Windows EXE a Inno Setup instalátor nelze na tomto hostu skutečně sestavit a spustit. |
| LOCAL-TEST-SUITE | Tests | PASS | passed=121, failed=0, skipped=2; skipped GUI test není release PASS. |
| LOCAL-COVERAGE-EVIDENCE | Tests | PASS | Lokální coverage=41.35 %. UI moduly nejsou bez PySide6 runtime pokryté a tento údaj nenahrazuje Windows GUI audit. |
| STATIC-LINT-TYPE-TOOLS | Static | BLOCKED | Nedostupné nástroje na tomto hostu: ['ruff', 'mypy'] |
| TRACEABILITY-162 | Audit | PASS | Chybějící řádky: [] |

## Blokované release gate

- `WINDOWS-RUN-BAT`
- `QT-GUI-DPI`
- `WINDOWS-EXE-INSTALLER`
- `STATIC-LINT-TYPE-TOOLS`
