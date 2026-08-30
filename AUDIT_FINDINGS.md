# Forenzní auditní zjištění – KájovoKarty 1.1

## Rozsah

Audit porovnal celý repozitář s autoritativním SSOT 1.1, jeho 162 akceptačními scénáři, 38 centrálními akcemi, 76 strukturálními UI komponentami a objektovou maticí Přílohy B. Kontrola zahrnovala zdrojový kód, migrace, testy, importy, matching, undo/redo, audit, bezpečnost, UI vazby, bootstrap a build podklady.

## Nalezené a opravené odchylky

1. **Chybný SQL dotaz Booking zdrojů.** Vyhledávání četlo `payment_id` z tabulky, která tento sloupec nemá. Dotaz nyní používá autoritativní vazbu na `booking_payout_batch`.
2. **Neúplná živá dohledatelnost objektů Přílohy B.** Doplněny indexy a vztahové projekce pro Allocation, ImportRun, karanténní řádek, AuditEvent, kandidát, Booking reference, účet, položku účtu a upozornění na změnu zdroje.
3. **Chybějící ruční řešení konfliktu Booking reference.** Doplněno potvrzení a odmítnutí s command historií, before/after auditem a undo/redo.
4. **Neúplné read-only obnovení API objektů.** Doplněno bezpečné GET obnovení Bill a BillItem; meta-only odpověď nemaže uložený snapshot.
5. **Dekorativní stavové prvky.** Dashboard aktuálnosti zdrojů, horní Stav zdrojů a Poslední běh nyní skutečně otevírají příslušný běh, Importy nebo Centrum operací.
6. **Dvojité spuštění obnovovaného Booking importu.** Duplicitní volání bylo odstraněno.
7. **Chybějící strojová matice Přílohy B.** Doplněn `docs/OBJECT_ACTION_MATRIX.json` a automatický test aplikovatelnosti všech povinných akcí.
8. **Zastaralé tvrzení o UI-24.** Tři normativní drop cíle – položka, karta skupiny a prázdné plátno – jsou přítomné v implementaci a pokryté statickým a integračním testem; skutečné vykreslení zůstává součástí Windows gate.
9. **Windows `run.bat` se v `cmd.exe` rozpadal na fragmenty.** Kořenovou příčinou byly LF-only konce řádků v dávkovém souboru. `run.bat` byl kompletně přepsán jako čisté ASCII bez BOM s výhradně CRLF, zjednodušeným řízením toku, kontrolou všech labelů a samostatným `build\run-bat.log`. Přidány regresní testy a `.gitattributes`, aby se chyba nevrátila.
10. **Bootstrap nepřijal režim `--run`.** `argparse` měl řetězce `--run`, `--check`, `--test` a `--repair` chybně definované jako poziční hodnoty. Proto je interpretoval jako neznámé přepínače a současně hlásil chybějící `mode`. Režimy jsou nyní deklarované jako povinná vzájemně výlučná skupina skutečných option flags a pokryté šesti novými regresními testy.
11. **Některá tlačítka byla na Windows nečitelná.** Globální `QWidget` styl přenesl světlé pozadí na potomky a pravidlo horní lišty nastavilo tlačítkům bílý text bez vlastní barvy pozadí. Výsledkem mohl být bílý text na světlém nativním tlačítku. Styl byl nahrazen centralizovaným tématem a explicitní `QPalette`; všechny interaktivní stavy mají pevný foreground i background. Přidán forenzní scan úniků hard-coded barev, WCAG výpočet kontrastu a runtime Qt test pro oba režimy.


## Výsledky dostupného auditu

- 121 testů prošlo, 0 selhalo, 2 GUI runtime testy byly přeskočeny kvůli chybějícímu PySide6.
- Statický kontrastní audit normálního i vysokokontrastního tématu prošel; všech 52 kritických párů splňuje nejméně 4,5:1 a minimum je 5,86:1.
- Všechny čtyři migrace se aplikovaly na čistou SQLite databázi; integrity a foreign-key kontrola prošly.
- Načteno a dohledáno všech 162 scénářů, 38 akcí a 76 UI komponent.
- Centrální registr pokrývá 15 objektových typů Přílohy B.
- Statický scan nenašel tokeny, původní vstupní dokumenty, nepravdivé EXE artefakty ani finanční výpočty přes `float` v kontrolovaných finančních cestách.
- Známé implementační odchylky po tomto opravném průchodu: **žádné zjištěné**.

## Verdikt

**BLOCKED**, nikoli PASS. Zbývají pouze release důkazy vyžadující skutečný Windows/Qt/tooling runtime; přesný seznam je v `BLOCKERS.json`. Bez jejich provedení nelze poctivě potvrdit instalátor, `run.bat`, DPI, přístupnost ani výsledné EXE.
