# Architektura KájovoKarty

KájovoKarty je lokální desktopový program pro Windows 10/11 x64. UI neprovádí přímé změnové zápisy do SQLite; změny procházejí aplikačními službami a explicitními commandy.

## Vrstvy

- `app` – cesty, preflight, bootstrap a sestavení služeb;
- `domain` – peníze v minor units, stavy, entity, Booking reference parser a deterministický matching;
- `application` – command/query služby, párování, vyhledávání protějšků, uložené filtry, karanténa, sestavy, audit, undo/redo a operace;
- `infrastructure` – Better Hotel read-only klient, importéry, SQLite, tajemství, logy a diagnostika;
- `ui` – PySide6 Widgets, centrální `ObjectActionRegistry`, obrazovky a dialogy.

## Datové a bezpečnostní invarianty

Better Hotel base URL je konstantní a integrační klient používá pouze GET. Tokeny nejsou ukládány v SQLite; na Windows používají DPAPI. Finanční vstupy se parsují přes `Decimal`, v databázi a výpočtech se používají integer minor units. Audit je append-only a undo/redo vytváří kompenzační příkazy.

SQLite se otevírá s `foreign_keys=ON`, WAL a busy timeoutem. Migrace jsou verzované v `migrations/`, před změnou existující databáze vzniká záloha a po migraci probíhá integrity check.

## Importní a párovací služby

`ImportPreflightService` před zařazením souboru ověřuje typ, velikost, hash, schéma, počet řádků, měny a pravděpodobnou duplicitu. Neznámé nebo nebezpečné řádky jsou dostupné v živé karanténě.

`ReconciliationService` a `ManualAllocationService` oddělují detailní Allocation od agregovaného vyrovnání. `CounterpartSearchService` poskytuje vysvětlitelné, read-only hledání v oknech 7/14/30 dní nebo za celé období a nikdy samo necommitne ruční rozhodnutí.

## UI a souběh

Centrální `ObjectActionRegistry` poskytuje jednotná ID, názvy, zkratky, tooltipy a handlery. Drag-and-drop payload nese pouze identifikátory a row version; autoritativní data se při dropu znovu načtou a validují.

API synchronizace, importy, matching, exporty a zálohy jsou navrženy přes `OperationManager` mimo UI vlákno s heartbeat, průběhem a kooperativním zrušením. Skutečný Qt/Windows runtime důkaz zůstává součástí otevřeného release gate.
