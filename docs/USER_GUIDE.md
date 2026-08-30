# Uživatelská příručka

1. Rozbalte balík do libovolné složky, včetně cesty s mezerami nebo českými znaky.
2. Na Windows 10/11 x64 spusťte dvojklikem `run.bat`.
3. Tokeny Better Hotel zadejte v **Nastavení → Připojení Better Hotel**. Aplikace se otevře i bez tokenů.
4. V **Importy a synchronizace** přidejte Booking.com CSV nebo bankovní CSV/XLS/XLSX. Před zařazením se zobrazí typ, velikost, hash, schéma, řádky, měny a případná duplicita.
5. Karanténu otevřete z importní obrazovky. U každého řádku lze zobrazit původní obsah, nastavit význam, znovu jej zpracovat nebo jej vědomě ignorovat.
6. Hlavní tlačítko **Aktualizovat a spárovat** spustí vědomě celý pracovní tok.
7. V **Párování** lze položky spojovat drag-and-drop, centrálními akcemi nebo pracovním výběrem. Náhled dropu ukazuje přesnou, částečnou, zakázanou či konfliktní variantu a konkrétní důvod.
8. Akce **Najít možné protějšky** nabízí vysvětlitelné výsledky pro 7, 14, 30 dní nebo celé období. Vzdálené výsledky zůstávají návrhem k ručnímu rozhodnutí.
9. Ruční změny lze vracet `Ctrl+Z` a opakovat `Ctrl+Y`; auditní historie se nemaže.
10. Ve **Vyhledávání** a **Sestavách** lze ukládat a znovu používat pojmenované filtry.

## Režimy `run.bat`

- `run.bat` – kontrola prostředí a spuštění GUI;
- `run.bat --check` – kontrola prostředí, souborů, závislostí a databáze bez GUI;
- `run.bat --test` – kontrola a automatické testy;
- `run.bat --repair` – nové `.venv` a opětovná instalace uzamčených závislostí.

Tento předaný stav je označen `BLOCKED`, protože skutečný Windows runtime, DPI audit a instalační artefakty nebylo možné v dostupném prostředí ověřit.
