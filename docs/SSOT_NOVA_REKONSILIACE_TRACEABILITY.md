# Dohledatelnost SSOT nové rekonsiliace

Implementované části dokumentu `KajovoKarty_SSOT_nova_rekonsiliace_2026-09-07.md`:

Scénáře nového SSOT: IMP-001 IMP-002 IMP-003 IMP-004 IMP-005 IMP-006 IMP-007 IMP-008; REC-001 REC-002 REC-003 REC-004 REC-005 REC-006 REC-007 REC-008 REC-009 REC-010 REC-011 REC-012; AUTO-001 AUTO-002 AUTO-003 AUTO-004 AUTO-005 AUTO-006; UI-001 UI-002 UI-003 UI-004 UI-005 UI-006 UI-007 UI-008.

| Scénář | Důkaz |
|---|---|
| IMP-001 až IMP-003 | `CashbookFileImportService`, `tests/integration/test_cashbook_reconciliation.py` |
| IMP-004, IMP-007, IMP-008 | konflikt identity je odmítnut před commitem, bez karantény a bez změny aktivních vazeb |
| REC-003, REC-007, REC-009, REC-010 | `ManualAllocationService.pair_sources`, `add_sources_to_group` a integrační testy |
| UI-003 | pokladní zdroj je v `SearchService.rebuild_index` |

Pokladní zdroj je uložen v nové migraci `006_cashbook_reconciliation.sql`. Import podporuje CSV, XLSX i XLS, normalizuje identifikátory, rozlišuje příjem/výdaj podle skutečných sloupců, zahazuje systémové a nekaretní řádky a ukládá immutable kanonický obsah s hashí.

Skupiny složené ze zdrojů používají přesný příspěvek: `CASHBOOK_CARD` kladně, `CARD` a `BOOKING` záporně. Nulový rozdíl je jediný stav `AGGREGATE_MATCHED`; nenulový rozdíl zůstává otevřeným pracovním objektem.

Zachované části původního dokladového toku zůstávají kompatibilní. Úplné Windows ověření zobrazení nové položky v párovacím pohledu a skutečného Better Hotel XLS exportu vyžaduje odpovídající runtime data; lokální unit/integration a UI kolekce nyní procházejí.
