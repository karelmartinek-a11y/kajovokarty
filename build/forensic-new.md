# Forenzní audit KájovoKarty proti SSOT 1.1

**Verdikt: BLOCKED**

SSOT SHA-256: `4d85c0cd84523758fcafbaa1de8863849684d066da8a2f13d9857de5f061ffb7`

| ID | Oblast | Stav | Zjištění |
|---|---|---|---|
| SSOT-NEW-IDENTITY | SSOT | PASS | Nový SSOT; chybí=[] |
| SSOT-NEW-ACCEPTANCE-CARDINALITY | SSOT | PASS | SSOT=34, očekáváno=34, chybí=[], přebývá=[] |
| UI-ACTION-REGISTRY | UI | PASS | enum=40, specs=40, přesné odchylky=[] |
| UI-ACTION-HANDLERS | UI | PASS | Akce bez dohledatelného handleru: [] |
| UI-OBJECT-ACTION-MATRIX | UI | PASS | Objekty=15, chybějící vazby=[] |
| UI-COMPONENT-REGISTRY | UI | PASS | enum=76, specs=76, přesné odchylky=[] |
| UI-COMPONENT-LIVE-BINDINGS | UI | PASS | Komponenty bez dohledatelné živé vazby: [] |
| SSOT-NEW-CONTRACT | Implementation | PASS | Odchylky: [] |
| REPO-TREE | Repository | PASS | Chybí: [] |
| REPO-SECRETS | Security | PASS | Nálezy: [] |
| REPO-PLACEHOLDERS | Repository | PASS | Nálezy: [] |
| REPO-NO-INPUTS | Security | PASS | Nálezy: [] |
| PY-AST | Static | PASS | Chyby: [] |
| MONEY-NO-FLOAT | Finance | PASS | Nálezy: [] |
| API-READ-ONLY | API | PASS | forbidden=[], endpoint=True, headers=True |
| DB-MIGRATIONS | Database | PASS | migrace=[1, 2, 3, 4, 5, 6, 7], integrity=ok, foreign_key_errors=0 |
| BOOTSTRAP-STATIC | Build | PASS | ASCII bez BOM, výhradně CRLF. |
| BUILD-REPRODUCIBLE-STATIC | Build | PASS | Chybí: [] |
| WINDOWS-RUN-BAT | Runtime | PASS | cmd.exe run.bat --check exit=0. |
| QT-GUI-DPI | UI runtime | PASS | PySide6 lze importovat. |
| WINDOWS-EXE-INSTALLER | Build | BLOCKED | Windows EXE a Inno Setup instalátor nelze na tomto hostu skutečně sestavit a spustit. |
| LOCAL-TEST-SUITE | Tests | PASS | passed=130, failed=0, skipped=0; skipped GUI test není release PASS. |
| LOCAL-COVERAGE-EVIDENCE | Tests | PASS | Lokální coverage=62.31 %. UI moduly nejsou bez PySide6 runtime pokryté a tento údaj nenahrazuje Windows GUI audit. |
| STATIC-LINT-TYPE-TOOLS | Static | PASS | ruff a mypy jsou dostupné. |
| TRACEABILITY-NEW-SSOT | Audit | PASS | Chybějící scénáře: [] |

## Blokované release gate

- `WINDOWS-EXE-INSTALLER`
