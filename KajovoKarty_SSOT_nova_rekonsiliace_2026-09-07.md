# KájovoKarty — návrh nového SSOT pro rekonsiliaci karetních příjmů

**Dokument:** normativní technická specifikace / podklad pro nahrazení nebo zásadní revizi SSOT KájovoKarty  
**Stav:** DRAFT k převzetí do autoritativního SSOT  
**Datum:** 2026-09-07  
**Cílový produkt:** KájovoKarty  
**Cílová platforma:** lokální desktopová aplikace Windows, Python / PySide6 / SQLite  
**Zásadní provozní vlastnost:** aplikace nemá uživatele, role ani přihlášení a nemá je mít.

---

## 0. Účel tohoto dokumentu

Tento dokument nově definuje účel a požadované chování programu KájovoKarty z pohledu skutečného pracovního procesu.

Program není primárně evidencí vystavených dokladů. Je to **rekonsiliační a kontrolní pracovní nástroj**, jehož úkolem je průběžně dokazovat, že karetní pohyby evidované v pokladním deníku Better Hotel jsou finančně vysvětlené a že současně nezůstávají bez vysvětlení ani relevantní transakce z bankovního/karetního transakčního exportu ani transakce Booking.com.

Program musí umožnit:

1. import skutečného pokladního deníku Better Hotel se zaměřením na karetní pohyby;
2. import bankovních/karetních transakcí;
3. import Booking.com platebních transakcí;
4. pomocnou synchronizaci dokladů, rezervací a vazeb z Better Hotel API;
5. automatické párování jednoznačných případů;
6. úplné ruční párování, seskupování, započítávání a rozpojování libovolných relevantních položek napříč zdroji;
7. jeden aktuální pohled na vše, co dosud není finančně vyřízeno;
8. přísnou idempotenci importů;
9. technickou auditní stopu všech změn;
10. práci v CZK a EUR bez jejich směšování nebo automatického přepočtu.

Tento dokument záměrně mění některé dosavadní koncepce aplikace. Zejména:

- **pokladní deník s karetními pohyby se stává primárním finančním zdrojem povinností;**
- vystavené doklady Better Hotel přestávají být primárním párovacím objektem a stávají se především pomocným identifikačním mostem;
- importní dávka není uživatelská pracovní jednotka;
- karanténa není součást cílového pracovního modelu;
- uživatel se nemá probírat jednotlivými návrhy automatického párování — jednoznačné případy se po výslovném spuštění automatického párování rovnou uzavřou;
- hlavní pracovní plocha nemá být rozdělena na tři izolované tabulky, ale má zobrazovat **jeden společný seznam všech nevyřízených pracovních objektů**.

---

# 1. Základní obchodní cíl

## 1.1 Definice cílového stavu

Cílovým stavem je situace, kdy:

- žádný relevantní karetní pohyb z pokladního deníku nezůstává bez finančního vysvětlení;
- žádná relevantní bankovní/karetní transakce nezůstává bez finančního vysvětlení;
- žádná relevantní Booking.com transakce nezůstává bez finančního vysvětlení;
- každá vyřízená věc je dohledatelná jako konkrétní seskupení zdrojových položek;
- jeden zdrojový záznam nesmí být použit dvakrát současně;
- již vyřízený objekt nesmí být novým importem samovolně rozpojen, přepsán ani změněn.

## 1.2 Co znamená „vyřízeno“

Finanční položka je vyřízena tehdy, když je součástí aktivního rekonsiliačního celku, jehož výsledný rekonsiliační rozdíl v dané měně je přesně nula.

Vyřízení může vzniknout například:

- pokladní deník 50 EUR ↔ Booking 50 EUR;
- pokladní deník 50 EUR ↔ banka 50 EUR;
- pokladní deník 50 EUR ↔ banka 10 EUR + Booking 40 EUR;
- pokladní deník 25 EUR + pokladní deník 25 EUR ↔ banka 50 EUR;
- Booking +50 EUR + Booking -50 EUR;
- banka +1 CZK + banka -1 CZK;
- libovolná jiná ručně vytvořená kombinace, pokud je měnově homogenní a její výsledný rekonsiliační rozdíl je přesně 0.

Vyřízení nevyžaduje povinné textové zdůvodnění.

## 1.3 Nevyřízená položka není chyba programu

Nevyřízená položka je legitimní pracovní stav. Znamená pouze, že pro ni zatím nebyl nalezen nebo vytvořen úplný finanční protějšek.

Program nesmí:

- domýšlet chybějící peníze;
- generovat fiktivní platby;
- měnit zdrojový Better Hotel;
- automaticky mazat či stornovat externí záznamy;
- uzavírat nejednoznačné případy pouze proto, aby dashboard vypadal čistě.

---

# 2. Autorita jednotlivých zdrojů

Program pracuje se čtyřmi datovými oblastmi, ale pouze tři z nich jsou finanční pracovní zdroje.

## 2.1 `CASHBOOK_CARD` — karetní pohyby pokladního deníku Better Hotel

**Role:** primární registr toho, co bylo v hotelovém systému zaúčtováno jako karetní pohyb.

Tento zdroj je hlavní osou kontroly. Typická kladná položka znamená: „v Better Hotel bylo zaevidováno, že tato částka byla přijata kartou a musí mít finanční vysvětlení“.

Zdroj musí obsahovat i záporné pohyby a storna, pokud jsou v pokladním deníku.

## 2.2 `BANK_CARD` — bankovní/karetní transakční export

**Role:** finanční důkaz, že karetní transakce skutečně existovala v karetním/bankovním transakčním zdroji.

Stávající implementace KájovoKarty pracuje s exportem obsahujícím například:

- Typ transakce
- ID Terminálu
- ID POS
- Datum a čas vzniku
- Čas připsání na server
- Datum zaúčtování
- Částka
- Cashback
- Spropitné
- Měna
- ARN kód
- DCC
- Číslo karty / číslo účtu
- Autorizační kód
- Variabilní symbol
- Variabilní symbol 2
- SEQ ID
- Vydavatel karty
- Způsob načtení karty
- Obchodní místo
- Adresa obchodního místa

Tento datový kontrakt se má zachovat, pokud konkrétní export banky/acquirera zůstává stejný.

## 2.3 `BOOKING` — Booking.com platební transakce

**Role:** finanční důkaz úhrady realizované prostřednictvím Booking.com.

Stávající importní kontrakt obsahuje:

- Typ faktury
- Číslo rezervace
- Datum příjezdu
- Checkout
- Jméno hosta
- Poskytovatel platebních služeb
- Status rezervace
- Měna
- Status platby
- Částka
- Datum vyplacení částky
- ID platby

Booking je plnohodnotný finanční pracovní zdroj stejně jako banka. Nejde pouze o doplňkovou informaci.

## 2.4 `BETTER_HOTEL_HELPER` — doklady, rezervace a další API data

**Role:** pomocná identifikační a vysvětlující vrstva.

Typický řetězec:

`pokladní pohyb → doklad → rezervace → Booking číslo → Booking transakce`

Doklad, rezervace ani API snapshot nejsou samy o sobě finančním protějškem, pokud SSOT výslovně neurčí jinak. Jejich primární úlohou je pomoci bezpečně a jednoznačně propojit finanční zdroje.

Doklady a rezervace se proto standardně nezapočítávají do rekonsiliačního součtu.

---

# 3. Ruční řízení, nikoliv tichá služba

## 3.1 Synchronizace Better Hotel

Aplikace musí mít zřetelné tlačítko například:

**Načíst / aktualizovat Better Hotel**

Tlačítko provede explicitní čtení aktuálních pomocných dat z Better Hotel API.

Synchronizace:

- se nespouští jako skrytá nepřetržitá služba;
- může mít technické automatické pomocné operace po spuštění aplikace pouze tehdy, pokud to bude později výslovně přidáno do SSOT;
- nesmí měnit data v Better Hotel;
- nesmí sama rozpojovat existující rekonsiliační skupiny;
- po dokončení zobrazí stručný souhrn výsledku.

## 3.2 Automatické párování

Aplikace musí mít zřetelné tlačítko například:

**Spustit automatické párování**

Po jeho stisknutí program:

1. vezme **aktuální stav celé databáze**, nikoliv poslední importní dávku;
2. vyhledá jednoznačně uzavíratelné případy;
3. jednoznačné případy přímo spáruje;
4. nevyžaduje potvrzení každé jednotlivé transakce;
5. nejednoznačné nebo neúplné případy ponechá nevyřízené;
6. po doběhu zobrazí souhrn.

Příklad souhrnu:

- analyzováno: 824 pracovních objektů;
- automaticky vyřízeno: 731;
- vytvořeno skupin: 716;
- zůstává nevyřízeno: 93;
- CZK: 61 nevyřízených;
- EUR: 32 nevyřízených.

---

# 4. Importní dávka není pracovní objekt

## 4.1 Základní pravidlo

Uživatel nikdy „nezpracovává dávku“.

Importní dávka je pouze technická evidence jednoho spuštění importu a jeho původu.

Po importu se nové položky okamžitě stanou součástí globálního stavu aplikace.

Veškeré:

- párování;
- automatické párování;
- vyhledávání;
- filtrování;
- dashboard;
- skupiny;
- exporty;

pracují vždy nad **celou aktuální databází**.

## 4.2 Přípustná technická evidence importu

Aplikace smí evidovat:

- název souboru;
- SHA-256 souboru;
- čas importu;
- počet řádků;
- počet nových řádků;
- počet identických již známých řádků;
- počet ignorovaných nerelevantních řádků;
- výsledné součty podle měn;
- stav operace.

Tato evidence však nesmí vytvářet oddělenou pracovní frontu.

---

# 5. Idempotence a zákaz duplicit

Toto je kritický invariant celého programu.

## 5.1 Opakovaný roční import je normální provozní scénář

Uživatel může opakovaně importovat například **celou knihu za celý rok**.

Program musí:

- poznat již známé záznamy;
- již známé identické záznamy znovu nevložit;
- přidat pouze skutečně nové záznamy;
- nijak nezměnit již existující párování;
- nijak nezměnit již existující skupiny;
- nijak nezměnit jejich auditní historii;
- nezaložit duplicate pracovní objekty.

## 5.2 Identický nebo jiný

Pro každý zdroj musí existovat definovaná:

1. **přirozená identita zdrojového záznamu**;
2. **kanonická reprezentace obsahu**;
3. **content hash**.

Výsledek porovnání je pouze:

### A. Stejná identita + stejný kanonický obsah

Výsledek: **identický záznam**.

- záznam se ignoruje;
- nevzniká nový finanční objekt;
- nevzniká nový člen pracovní fronty;
- nemění se rekonsiliace;
- nemění se skupiny.

### B. Nová přirozená identita

Výsledek: **nový záznam**.

- po úspěšném preflightu se vloží;
- objeví se v globálním pracovním stavu.

### C. Stejná přirozená identita + jiný kanonický obsah

Výsledek: **tvrdý konflikt zdroje**.

Cílové SSOT nepoužívá karanténu.

Import se musí zastavit **před commitem celé importní operace**.

Databáze zůstane přesně ve stavu před spuštěním importu.

Uživateli se zobrazí:

- zdroj;
- identifikátor;
- číslo řádku;
- která pole se liší;
- srozumitelné sdělení, že zdrojový export obsahuje rozdílná data pod již známou identitou.

## 5.3 Co znamená „duplikát nesmí vstoupit ani do pracovního režimu“

Parser samozřejmě může řádek dočasně načíst do paměti, aby jej mohl ověřit.

SSOT však zakazuje jeho **logickou materializaci**:

identický řádek nesmí získat nový doménový identifikátor, stav, členství ve skupině, dashboardový řádek, index pracovního objektu ani jiný persistentní či pracovní životní cyklus.

---

# 6. Atomický import

Každý import má dvě logické fáze.

## 6.1 Preflight

Preflight:

- načte neměnný snapshot zdrojového souboru;
- ověří typ souboru;
- ověří hlavičky;
- normalizuje hodnoty;
- ověří měny;
- vypočítá přirozené identity;
- vypočítá kanonické hashe;
- zjistí identické řádky;
- zjistí nové řádky;
- zjistí tvrdé konflikty;
- nic nemění v doménové databázi.

## 6.2 Commit

Commit může začít pouze po úspěšném preflightu.

Commit:

- proběhne v jedné DB transakci;
- vloží pouze nové řádky;
- při jakékoli chybě provede rollback celé operace;
- nikdy nezapisuje část souboru a zbytek neodmítne.

## 6.3 Soubor se během importu nesmí změnit

Před commitem se musí ověřit, že snapshot/hash souboru odpovídá preflightu.

---

# 7. Pokladní deník Better Hotel — import karetních pohybů

## 7.1 Zdrojový formát

Struktura se přebírá z importu pokladní knihy KájovoVýdaje2.

Podporovaný cílový vstup je historický Better Hotel `.xls` export se sloupci:

1. `Vystaveno`
2. `Pohyb`
3. `Číslo`
4. `Označení`
5. `Klient`
6. `Příjem`
7. `Výdaj`
8. `Stav pokladny`
9. `Měna`
10. `Forma úhrady`
11. `Pokladna`
12. `Variabilní symbol`
13. `Vystavil`

Preferovaný list je `Worksheet`.

Není-li přítomen, musí existovat právě jeden viditelný list se správnou hlavičkou.

## 7.2 Normalizace hlaviček a identifikátorů

Přebírá se princip KájovoVýdaje2:

- Unicode NFKC;
- odstranění BOM;
- odstranění okolních mezer;
- identifikátory zůstávají textem;
- řetězcové nuly se zachovávají;
- `123.0` vzniklé typovou interpretací Excelu se může pro identifikátor normalizovat na `123`, pokud je matematicky celočíselné;
- HTML entity v textových polích se mohou dekódovat;
- datum/čas se interpretuje v `Europe/Prague` a ukládá se v UTC.

## 7.3 Výběr relevantních řádků

Do finančního zdroje `CASHBOOK_CARD` vstupují pouze skutečné karetní pohyby.

Řádky typu:

- Počáteční stav
- Uzávěrka
- Konečný stav

nejsou finančními pracovními objekty.

`Forma úhrady` se kanonizuje na význam.

Do `CASHBOOK_CARD` vstupuje pouze význam `CARD`.

Konkrétní surové názvy, které Better Hotel používá pro kartu, musí být určeny z reálného exportu a mapovány deterministicky. SSOT nesmí předpokládat název, který nebyl ověřen na reálných datech.

Řádky jiné formy úhrady nejsou chybou; jsou pro KájovoKarty nerelevantní a při importu se pouze započítají do technického počtu ignorovaných řádků.

## 7.4 Důležitá odlišnost od KájovoVýdaje2

Z KájovoVýdaje2 se přebírá:

- struktura souboru;
- normalizace;
- detekce systémových řádků;
- robustní čtení XLS;
- identitní a hash princip;
- preflight;
- atomický commit;
- idempotence.

**Nepřebírají se obchodní filtry specifické pro program KájovoVýdaje2.**

Zejména se nesmí slepě převzít:

- omezení pouze na CZK;
- ignorování řádků „úhrada dokladu/faktury“;
- účetní cutoff určený pro KájovoVýdaje2;
- pravidlo určené pouze pro hotovostní výdaje.

KájovoKarty naopak potřebuje karetní úhrady právě proto, aby je mohl rekonsiliovat.

## 7.5 Směr pohybu a částka

Autoritativní je skutečné naplnění sloupců `Příjem` / `Výdaj`.

- `Příjem > 0` a `Výdaj = 0` → kladný pohyb.
- `Příjem = 0` a `Výdaj > 0` → záporný pohyb.
- obě hodnoty kladné → neplatný relevantní řádek, import selže;
- obě hodnoty nulové → nerelevantní nulový pohyb.

Sloupec `Pohyb` je kontrolní údaj, nikoliv jediný zdroj znaménka.

## 7.6 Měny

KájovoKarty podporuje:

- `CZK`
- `EUR`

Žádná konverze se neprovádí.

Částky se ukládají v minor units:

- 1 CZK = 100 haléřů;
- 1 EUR = 100 centů.

Zdrojová hodnota nesmí mít přesnost vyšší než dvě desetinná místa.

## 7.7 Přirozená identita pokladního pohybu

Primární přirozenou identitou je normalizované číslo Better Hotel pokladního dokladu z pole `Číslo`, typicky PVD/PPD.

Normativní pravidlo:

`cashbook_identity = normalize(PVD/PPD)`

Kanonický obsah zahrnuje minimálně:

- datum a čas;
- odvozený směr pohybu;
- normalizované číslo;
- označení;
- klienta;
- signed amount;
- měnu;
- formu úhrady;
- pokladnu;
- variabilní symbol;
- vystavil.

`cashbook_content_hash = SHA256(canonical_json(canonical_fields))`

Stejná identita + stejný hash = identický řádek → ignorovat.

Stejná identita + jiný hash = tvrdý konflikt → rollback celého importu.

---

# 8. Bankovní/karetní transakční import

## 8.1 Podporované formáty

Stávající KájovoKarty podporuje:

- CSV
- XLS
- XLSX

Tato schopnost se zachovává.

## 8.2 Přirozená identita

Stávající zdroj obsahuje `ID Terminálu` a `SEQ ID`.

Normativní identita:

`bank_card_identity = normalize(terminal_id) + "|" + normalize(seq_id)`

Tyto hodnoty nesmí být prázdné u relevantního prodeje/refundace.

## 8.3 Kanonický obsah

Content hash musí pokrýt celý významový finanční řádek, minimálně:

- typ transakce;
- terminal ID;
- POS ID;
- datum/čas vzniku;
- server timestamp;
- datum zaúčtování;
- částku;
- měnu;
- cashback;
- spropitné;
- DCC;
- ARN;
- autorizační kód;
- maskovanou kartu / účet;
- VS / VS2;
- SEQ ID;
- vydavatele;
- způsob načtení;
- obchodní místo;
- adresu.

Stejná `bank_card_identity` + stejný canonical hash = identický záznam.

Stejná `bank_card_identity` + jiný obsah = tvrdý konflikt importu, nikoliv karanténa.

## 8.4 Typy transakcí

Relevantní finanční typy zahrnují zejména:

- prodej;
- refundaci;
- storno;
- vrácení.

Uzávěrky, souhrnné řádky a prázdné řádky nejsou finanční pracovní objekty.

Pokud import narazí na neznámý typ, který nelze jednoznačně klasifikovat jako nerelevantní technický řádek, musí preflight import odmítnout s přesným číslem řádku a hodnotou.

Cílové SSOT zde nepoužívá karanténu.

## 8.5 Znaménko

Prodej je kladná finanční transakce.

Refundace/storno/vrácení je záporná finanční transakce.

Pokud zdroj exportuje refundaci kladně, parser ji podle typu bezpečně kanonizuje na zápornou.

---

# 9. Booking.com import

## 9.1 Podporovaný formát

Booking import je CSV s přesně definovanou významovou hlavičkou.

Minimální požadovaná pole:

- Typ faktury
- Číslo rezervace
- Datum příjezdu
- Checkout
- Jméno hosta
- Poskytovatel platebních služeb
- Status rezervace
- Měna
- Status platby
- Částka
- Datum vyplacení částky
- ID platby

## 9.2 Povinné identifikátory

Relevantní řádek musí mít:

- `Číslo rezervace`;
- `ID platby`;
- `Datum vyplacení částky`;
- `Měna`;
- `Částka`.

## 9.3 Přirozená identita

Vychází z aktuálního KájovoKarty kontraktu a musí být stabilní vůči opakovaným ročním exportům.

Normativní zdrojová identita:

`booking_identity = SHA256(payment_id, reservation_number, currency, payout_date, invoice_type)`

Kromě ní se vede:

`booking_row_hash = SHA256(payment_id, reservation_number, currency, amount_minor, payout_date, arrival, checkout, invoice_type, payment_status)`

a úplný `booking_content_hash` z kanonizovaného významového řádku.

Stejná přirozená identita + stejný obsah = identický záznam.

Stejná přirozená identita + jiný finanční obsah = tvrdý konflikt importu a rollback.

## 9.4 Statusy

Relevantnost Booking řádku může být odvozena z mapovaných významů `Status rezervace` a `Status platby`.

Mapování musí být deterministické a uložené v konfiguraci/databázi, ne skryté v UI.

Neznámý význam relevantního statusu nesmí být tiše přijat.

Cílově:

- jasně nerelevantní stav → řádek ignorovat a započítat v technickém souhrnu;
- neznámý stav, u kterého nelze bezpečně určit relevanci → import odmítnout v preflightu.

Žádná karanténa.

---

# 10. Better Hotel API jako pomocný identifikační most

## 10.1 Co se synchronizuje

Aplikace může z Better Hotel API číst zejména:

- vystavené doklady;
- identifikátory dokladů;
- částku a měnu dokladu;
- vazbu dokladu na rezervaci;
- interní kód rezervace;
- Booking.com referenci rezervace;
- další údaje potřebné pro vysvětlení vazby.

## 10.2 Pomocná data nejsou finanční peníze

Pomocný doklad:

- nevytváří sám o sobě plus/mínus v rekonsiliaci;
- nesmí být použit jako náhrada za skutečnou bankovní nebo Booking transakci;
- slouží k nalezení správného protějšku.

## 10.3 Refresh pomocných dat

Aktualizace helper dat:

- může doplnit nové vztahy pro dosud nevyřízené položky;
- může změnit zobrazený kontext;
- nesmí sama zrušit existující vyřízenou skupinu;
- nesmí měnit immutable finanční source rows.

---

# 11. Jednotný finanční model

Každá finanční zdrojová položka musí mít minimálně:

- `id`
- `source_kind`
- `source_identity`
- `source_document_id`
- `occurred_at`
- `signed_amount_minor`
- `currency_code`
- `content_hash`
- `raw_source_snapshot`
- `created_at`
- odkaz na importní provenance
- stav aktivního pracovního vlastnictví

## 11.1 Rekonsiliační příspěvek

Aby bylo možné počítat jednu skupinu přes různé zdroje, zavádí se jednotný `reconciliation_contribution_minor`.

### `CASHBOOK_CARD`

`contribution = signed_amount_minor`

### `BANK_CARD`

`contribution = -signed_amount_minor`

### `BOOKING`

`contribution = -signed_amount_minor`

### `BETTER_HOTEL_HELPER`

`contribution = 0`

Tím vzniká jednotná matematika:

Pokladní deník +50 EUR a Booking +50 EUR:

`+5000 + (-5000) = 0`

Pokladní deník +50 EUR, banka +10 EUR, Booking +40 EUR:

`+5000 -1000 -4000 = 0`

Booking +50 EUR a Booking -50 EUR:

`-5000 +5000 = 0`

Banka +1 CZK a banka -1 CZK:

`-100 +100 = 0`

---

# 12. Rekonsiliační skupina

## 12.1 Skupina je plnohodnotný pracovní objekt

Skupina není pouze dekorativní vazba.

Po vytvoření se navenek chová stejně jako jednotlivý pracovní řádek.

Může být:

- filtrována;
- vyhledána;
- označena;
- použita při dalším párování;
- vložena do další skupiny;
- rozpojena;
- exportována;
- otevřena do detailu.

## 12.2 Skupina může být nevyřízená

Toto je zásadní.

Skupina nemusí mít při vytvoření nulový rozdíl.

Příklad:

- banka 10 EUR;
- Booking 40 EUR.

Uživatel je spojí.

Výsledkem je jeden skupinový pracovní objekt s efektem „zdroj úhrady 50 EUR“.

Tento objekt zůstane v hlavním nevyřízeném seznamu a může být později spojen s pokladním deníkem 50 EUR.

## 12.3 Skupina se stejným zdrojem

Příklad:

- pokladní deník 25 EUR;
- pokladní deník 25 EUR.

Po seskupení vznikne jeden pracovní objekt „pokladní deník 50 EUR“.

Příklad:

- Booking +50 EUR;
- Booking -50 EUR.

Výsledek skupiny je 0 a skupina je rovnou vyřízena jako vnitrozdrojové započtení.

## 12.4 Odvozená pracovní strana skupiny

Pro skupinu se spočítá:

`group_contribution = SUM(contribution všech aktivních listových členů)`

Je-li:

- `group_contribution > 0`: skupina představuje zbývající pokladní povinnost / potřebu krytí;
- `group_contribution < 0`: skupina představuje přebytek finančního zdroje;
- `group_contribution = 0`: skupina je finančně vyřízena.

## 12.5 Měnový invariant

Jedna aktivní skupina smí obsahovat pouze jednu měnu.

CZK a EUR se nikdy nesmějí vložit do stejné rekonsiliační skupiny.

## 12.6 Přesná rovnost

Vyřízení vyžaduje:

`group_contribution == 0`

Bez tolerance.

Žádných ±0,01, žádné „skoro sedí“.

Pokud je rozdíl nenulový, skupina je pracovní nevyřízený objekt.

## 12.7 Kompozice skupin

Uživatel smí vybrat:

- jednotlivý záznam + jednotlivý záznam;
- záznam + skupinu;
- skupinu + skupinu;
- libovolný počet objektů.

Implementace musí při finančním výpočtu vždy pracovat s listovými zdrojovými položkami a zabránit dvojímu započtení.

## 12.8 Jeden aktivní rodič

Každý pracovní objekt smí mít nejvýše jedno aktivní nadřazené členství.

Tím se zajišťuje, že jeden finanční řádek nelze současně použít ve dvou nezávislých aktivních skupinách.

## 12.9 Rozpojování

Musí existovat dvě jasné operace:

### Rozpojit nadřazené párování

Zruší pouze vazbu na rodičovskou skupinu.

Pokud byly uvnitř již vytvořené podskupiny, ty zůstávají zachované a znovu se objeví jako samostatné pracovní objekty.

### Rozložit skupinu

Rozloží vybranou skupinu na její přímé děti.

Tím lze postupně rozebrat i víceúrovňovou konstrukci bez ztráty původních dat.

## 12.10 Poznámka

Skupina smí mít volitelnou poznámku.

Poznámka:

- není povinná;
- nemá minimální délku;
- není podmínkou vytvoření;
- není podmínkou rozpojení;
- není náhradou auditu.

---

# 13. Automatické párování

## 13.1 Zásada

Automatika má **přímo uzavírat jednoznačné případy**.

Nemá nutit uživatele odsouhlasovat každou položku.

## 13.2 Primární směr

Automatika začíná primárně od nevyřízených `CASHBOOK_CARD` položek.

Preferovaný řetězec pro Booking:

1. najít pokladní pohyb;
2. jednoznačně k němu najít Better Hotel doklad;
3. z dokladu získat rezervaci;
4. z rezervace získat Booking.com číslo;
5. najít odpovídající Booking transakci nebo jednoznačnou kombinaci Booking transakcí;
6. ověřit měnu;
7. ověřit přesný finanční součet;
8. vytvořit rekonsiliační skupinu;
9. označit vznik jako `AUTO`.

## 13.3 Doklad musí být jednoznačný

Automatika smí pokračovat pouze tehdy, pokud je vazba pokladní pohyb → doklad jednoznačná.

Preferované deterministické důkazy:

1. explicitní číslo dokladu obsažené ve zdrojovém pokladním řádku;
2. explicitní vazba dostupná ze synchronizovaných Better Hotel dat;
3. jiný jednoznačný identifikátor definovaný SSOT a ověřený na reálném exportu.

Pouhá podobnost jména hosta nestačí.

## 13.4 Booking vazba

Je-li doklad svázán s rezervací a rezervace má Booking reference:

- Booking reference musí být shodná;
- měna musí být shodná;
- výsledný součet musí být přesný.

Je-li pro tutéž referenci více Booking řádků, automatika je smí zkombinovat pouze tehdy, pokud existuje **jediná jednoznačná kombinace** dávající přesný součet.

## 13.5 Přímé bankovní/karetní párování

Automatika smí rovněž uzavírat `CASHBOOK_CARD ↔ BANK_CARD`, pokud je vazba jednoznačná.

Minimálně musí platit:

- stejná měna;
- přesná částka po znaménkové interpretaci;
- kompatibilní časové období;
- žádný druhý stejně vhodný nevyřízený kandidát.

Dostupné silné identifikátory jako autorizační kód, variabilní symbol, ARN nebo jiný explicitní společný identifikátor mají přednost před pouhou časovou blízkostí.

## 13.6 Časové okno

Stávající program pracuje s datumovými pásmy do 7 dní.

Nové SSOT může tuto schopnost zachovat jako vyhledávací omezení, ale:

- datum samo nikdy nesmí převážit měnu nebo částku;
- při více stejně možných kandidátech se automatické uzavření nesmí provést;
- změna okna nesmí změnit již existující ruční skupiny.

## 13.7 Automatika nesmí přepisovat ruční práci

Automatika nikdy:

- nerozpojí ruční skupinu;
- nepřesune členy ruční skupiny;
- nepoužije záznam, který již patří do jiného aktivního stromu;
- nepřepíše volitelnou poznámku;
- neopraví zdrojový záznam.

## 13.8 Opakované spuštění

Automatické párování musí být idempotentní vůči aktuálnímu stavu.

Pokud se mezi dvěma spuštěními nic nezměnilo, druhé spuštění nesmí vytvořit nové duplicity ani změnit již uzavřené skupiny.

---

# 14. Ruční práce

## 14.1 Globální výběr

Uživatel musí být schopen vybrat libovolné nevyřízené pracovní objekty napříč zdroji.

Výběr může obsahovat:

- pokladní položky;
- bankovní/karetní položky;
- Booking položky;
- nevyřízené skupiny.

## 14.2 Průběžný součet

Při výběru UI okamžitě zobrazuje:

- počet objektů;
- zdrojové badge;
- měnu;
- součet příspěvků;
- výsledný rozdíl;
- zda by potvrzení vedlo k vyřízení.

Je-li ve výběru více měn, UI zobrazí součty odděleně a nepovolí vytvoření jedné skupiny.

## 14.3 Rychlá práce

Běžný tok:

1. klik;
2. klik;
3. případně další kliky;
4. vytvořit skupinu / spárovat;
5. hotovo.

Žádné povinné psaní textového důvodu.

## 14.4 Povolené finanční kombinace

Musí fungovat:

- 1:1;
- 1:N;
- N:1;
- N:N;
- jedna zdrojová oblast proti jiné;
- dva zdroje finančního krytí proti jednomu pokladnímu záznamu;
- více pokladních záznamů proti jednomu zdroji;
- započtení v rámci jednoho zdroje;
- kombinace již existujících skupin.

---

# 15. Jeden společný dashboard

## 15.1 Výchozí obrazovka

Hlavním pracovním pohledem je:

**Nevyřízené**

Ne tři oddělené izolované tabulky.

Každý řádek představuje:

- jeden samostatný nevyřízený zdrojový záznam; nebo
- jednu nevyřízenou skupinu.

## 15.2 Zdroj je vlastnost, ne umístění

Řádek nese příznaky zdrojů například:

- POKLADNÍ DENÍK
- BANKA/KARTA
- BOOKING
- POKLADNÍ + BOOKING
- BANKA + BOOKING
- POKLADNÍ + BANKA + BOOKING

Zdroj určuje původ a kontext, nikoliv to, ve které oddělené obrazovce smí být objekt řešen.

## 15.3 Doporučené sloupce

Výchozí tabulka má obsahovat minimálně:

- stav;
- typ objektu;
- zdroje;
- datum / čas;
- hlavní identifikátor;
- popis / host / klient;
- počet členů;
- pracovní strana;
- částka;
- měna;
- rekonsiliační rozdíl;
- Booking reference;
- doklad;
- důvod nevyřízenosti;
- volitelná poznámka.

Sloupce musí být uživatelsky:

- přeskupitelné;
- skrývatelné;
- šířkově měnitelné;
- řaditelné.

Nastavení pohledu se ukládá lokálně.

## 15.4 Horní KPI

Dashboard má zobrazit nejméně:

- celkový počet nevyřízených pracovních objektů;
- nevyřízené pokladní povinnosti CZK;
- přebytek finančních zdrojů CZK;
- nevyřízené pokladní povinnosti EUR;
- přebytek finančních zdrojů EUR;
- počet nevyřízených čistých pokladních položek;
- počet nevyřízených bankovních položek;
- počet nevyřízených Booking položek;
- počet nevyřízených agregovaných skupin.

CZK a EUR nikdy nesmí být prezentovány jako jeden finanční součet.

---

# 16. Excel-like tabulky, filtry a fulltext

## 16.1 Obecný požadavek

Každá hlavní tabulka v programu se musí chovat jako profesionální datová mřížka, nikoliv jako pasivní seznam.

## 16.2 Třídění

Musí být možné:

- řadit podle libovolného zobrazitelného sloupce;
- vzestupně / sestupně;
- kombinovat více třídicích klíčů, pokud to UI knihovna umožňuje.

## 16.3 Filtry

Minimálně:

- zdroj / kombinace zdrojů;
- měna;
- kladný / záporný efekt;
- přesná částka;
- rozsah částky;
- datum od / do;
- typ objektu;
- samostatný záznam / skupina;
- důvod nevyřízenosti;
- Booking reference;
- PVD/PPD;
- SEQ ID;
- terminál;
- autorizační kód;
- ARN;
- variabilní symbol;
- doklad;
- rezervace.

## 16.4 Fulltext

Jedno centrální hledání musí hledat minimálně přes:

- PVD/PPD;
- číslo dokladu;
- interní ID dokladu;
- Booking číslo rezervace;
- ID platby Booking;
- jméno hosta;
- klienta;
- označení;
- variabilní symbol;
- SEQ ID;
- terminal ID;
- ARN;
- autorizační kód;
- volitelnou poznámku skupiny.

## 16.5 Kombinace filtrů

Filtry musí být kombinovatelné.

Příklad:

`EUR + Booking + nevyřízené + částka 50 + text "123456789"`

musí být běžný pracovní scénář.

## 16.6 Filtr nesmí měnit data

Filtrování je pouze projekce.

Nesmí:

- měnit členství ve skupinách;
- měnit výběry mimo explicitní uživatelskou akci;
- znovu importovat;
- měnit párovací stav.

---

# 17. Všechny akce všude

## 17.1 Jednotný action registry

Nad stejným typem objektu musí být dostupná stejná akce bez ohledu na to, kde byl objekt nalezen:

- hlavní dashboard;
- výsledky fulltextu;
- historie;
- detail;
- pohled podle zdroje;
- související položky.

## 17.2 Minimální globální akce

Podle kontextu musí být dostupné:

- Otevřít detail
- Zobrazit členy skupiny
- Zobrazit související helper data
- Přidat do pracovního výběru
- Odebrat z pracovního výběru
- Vyčistit pracovní výběr
- Vytvořit skupinu
- Přidat do skupiny
- Spárovat / uzavřít
- Rozpojit nadřazenou vazbu
- Rozložit skupinu
- Upravit volitelnou poznámku
- Najít možné protějšky
- Otevřít související doklad
- Otevřít související rezervaci
- Kopírovat hlavní identifikátor
- Kopírovat všechny identifikátory
- Exportovat vybrané
- Zobrazit auditní historii

Pokud akce pro konkrétní výběr nedává smysl, má být zakázaná s jasným důvodem, nikoliv implementována jiným způsobem v každé obrazovce.

---

# 18. Důvody nevyřízenosti

Důvod je technické vysvětlení stavu, nikoliv povinný komentář uživatele.

Doporučené stabilní kódy:

| Kód | Význam |
|---|---|
| `CASHBOOK_NO_DOCUMENT` | Pokladní pohyb nemá jednoznačně nalezený doklad |
| `DOCUMENT_NO_RESERVATION` | Doklad nemá vazbu na rezervaci |
| `RESERVATION_NO_BOOKING_REFERENCE` | Rezervace nemá Booking reference |
| `BOOKING_REFERENCE_NOT_FOUND` | Pro Booking reference není finanční řádek |
| `BANK_NO_COUNTERPART` | Bankovní/karetní transakce nemá protějšek |
| `BOOKING_NO_COUNTERPART` | Booking transakce nemá protějšek |
| `CASHBOOK_NO_COUNTERPART` | Pokladní pohyb zatím nemá finanční krytí |
| `AMOUNT_MISMATCH` | Kandidáti existují, ale přesný součet nesedí |
| `CURRENCY_MISMATCH` | Relevantní kandidáti jsou v jiné měně |
| `MULTIPLE_CANDIDATES` | Existuje více rovnocenných možností |
| `OPEN_AGGREGATE` | Ručně vytvořená skupina má nenulový výsledek |
| `HELPER_DATA_NOT_SYNCED` | Pro automatickou vazbu chybí aktuální helper data |

---

# 19. Matice důvod × akce × výsledek

| Důvod | Co zobrazit | Primární akce | Výsledek |
|---|---|---|---|
| `CASHBOOK_NO_DOCUMENT` | pokladní řádek + dostupné identifikátory | Najít doklad / otevřít helper hledání / ručně seskupit s finančním zdrojem | položka zůstane nevyřízená nebo se ručně uzavře |
| `DOCUMENT_NO_RESERVATION` | nalezený doklad | Otevřít doklad / znovu sync Better Hotel / ručně párovat | žádné automatické domýšlení |
| `RESERVATION_NO_BOOKING_REFERENCE` | rezervace bez Booking ID | Otevřít rezervaci / znovu sync / ruční finanční párování | bez povinné poznámky |
| `BOOKING_REFERENCE_NOT_FOUND` | Booking reference | filtrovat Booking podle reference / data / částky | ruční výběr nebo pozdější nový import |
| `BANK_NO_COUNTERPART` | bankovní řádek | Najít protějšky / vytvořit skupinu | může zůstat jako přebytek nebo být započten |
| `BOOKING_NO_COUNTERPART` | Booking řádek | Najít protějšky / vytvořit skupinu | může být spojen i s jiným Booking řádkem |
| `CASHBOOK_NO_COUNTERPART` | pokladní řádek | Najít protějšky / vytvořit skupinu | čeká na další import nebo opravu ve zdroji |
| `AMOUNT_MISMATCH` | očekávaný a nalezený součet | přidat další objekty do pracovního výběru | vznikne agregát nebo přesně vyřízená skupina |
| `CURRENCY_MISMATCH` | měny kandidátů | zobrazit správnou měnu / odstranit nesprávný výběr | nelze vytvořit smíšenou skupinu |
| `MULTIPLE_CANDIDATES` | seznam kandidátů | ručně vybrat správné | automatika nic neuzavře |
| `OPEN_AGGREGATE` | členové + net amount | přidat další objekt / rozložit skupinu | skupina zůstane jedním řádkem |
| `HELPER_DATA_NOT_SYNCED` | čas posledního sync | Načíst Better Hotel | pomocná data se obnoví |

---

# 20. Audit

## 20.1 Bez uživatelů

Aplikace nemá a nebude mít:

- uživatelské účty;
- role;
- autora změny;
- přihlášení.

Audit proto neobsahuje „kdo“.

## 20.2 Auditní událost

Každá významová změna musí vytvořit technickou auditní událost minimálně s:

- časem;
- typem operace;
- ID objektu;
- zdrojovými ID;
- stavem před;
- stavem po;
- měnou;
- částkou / rozdílem;
- metodou `AUTO` / `MANUAL` / `IMPORT` / `SYSTEM`;
- ID nadřazené operace;
- volitelnou poznámkou, pokud ji uživatel zadal.

## 20.3 Auditované operace

Minimálně:

- import zahájen;
- import dokončen;
- import odmítnut;
- Better Hotel sync;
- automatické párování spuštěno;
- automatická skupina vytvořena;
- ruční skupina vytvořena;
- objekt přidán do skupiny;
- vazba rozpojena;
- skupina rozložena;
- poznámka upravena;
- export vytvořen.

## 20.4 Audit není důvodovací formulář

Uživatel není nucen zapisovat důvod.

Audit si systém vytváří sám.

---

# 21. Sestavy a exporty

## 21.1 Nevyřízené

Export aktuálního pracovního seznamu se zachováním:

- aktivních filtrů;
- měny;
- zdrojů;
- identifikátorů;
- důvodů nevyřízenosti.

## 21.2 Vyřízené skupiny

Musí být možné vyexportovat:

- ID skupiny;
- čas vytvoření;
- metoda AUTO/MANUAL;
- měna;
- výsledný rozdíl;
- všechny listové členy;
- původ členů;
- pomocné vazby doklad / rezervace / Booking reference.

## 21.3 Rekonsiliační důkaz skupiny

Detail skupiny musí být exportovatelný jako tabulkový důkaz:

| Zdroj | Identifikátor | Datum | Signed amount | Contribution | Měna |
|---|---|---:|---:|---:|---|
| CASHBOOK_CARD | PVD… | … | +50 | +50 | EUR |
| BANK_CARD | TERM/SEQ… | … | +10 | -10 | EUR |
| BOOKING | reservation/payment… | … | +40 | -40 | EUR |
| **Celkem** |  |  |  | **0** | EUR |

## 21.4 Formáty

Minimálně:

- CSV;
- XLSX.

PDF může být doplněno jako prezentační formát, ale nesmí nahradit strojově použitelný export.

---

# 22. Měny

## 22.1 Podporované měny

Normativně:

- CZK
- EUR

## 22.2 Žádný automatický kurz

Program:

- nepřepočítává CZK na EUR;
- nepřepočítává EUR na CZK;
- nevyužívá kurz k uzavření skupiny.

## 22.3 Každý řádek nese vlastní měnu

V jednotném dashboardu jsou CZK a EUR položky společně ve stejné tabulce.

Měna je atribut řádku.

Oddělení měn se týká:

- finančních součtů;
- výpočtu skupin;
- párování;
- KPI;
- exportních součtů.

Neznamená to povinné oddělené tabulky.

---

# 23. Databázové invarianty

Databáze musí sama vynucovat kritické invariants, ne pouze UI.

## 23.1 Unikátnost zdrojů

Unikátní constrainty nebo ekvivalentní transakční kontroly musí existovat minimálně pro:

- `cashbook_identity`;
- `(terminal_id, seq_id)` bankovního zdroje;
- Booking přirozenou identitu / stabilní row identity.

## 23.2 Jedno aktivní vlastnictví

Jedna listová finanční položka nesmí být současně aktivně započítána ve dvou nezávislých top-level rekonsiliačních stromech.

## 23.3 Měna skupiny

DB operace musí odmítnout vytvoření skupiny s více měnami, i kdyby UI mělo chybu.

## 23.4 Výpočet nuly

Stav finančně vyřízeno může vzniknout pouze při přesném `SUM(contribution_minor) == 0`.

## 23.5 Source immutable

Importované finanční zdrojové řádky se po commitu nepřepisují jako běžný způsob aktualizace.

Při shodné identitě a odlišném obsahu se import odmítne.

---

# 24. Transakční bezpečnost a souběh

## 24.1 Všechny mutace atomicky

Operace:

- vytvoření skupiny;
- přidání členů;
- rozpojení;
- rozložení;
- automatické párování jednotlivé skupiny;

musí být DB transakce.

## 24.2 Optimistická ochrana proti zastaralému stavu

Pracovní objekty musí mít verzi / row version nebo jiný mechanismus.

Jestliže se objekt změnil od chvíle, kdy jej UI načetlo, mutace musí být odmítnuta a UI obnoveno.

## 24.3 Automatické párování

Před commitem každé automatické skupiny se znovu ověří:

- že všichni členové jsou stále dostupní;
- že měna zůstala stejná;
- že částky zůstaly stejné;
- že žádný člen mezitím nebyl ručně použit.

---

# 25. Historie a vratnost

## 25.1 Zdrojová data se nemažou

Rozpojení skupiny nemaže importovaný finanční řádek.

## 25.2 Historie skupiny

Po rozpojení zůstává historická skupina dohledatelná v auditu, ale není aktivní ve finančním výpočtu.

## 25.3 Undo/Redo

Pokud stávající program zachová obecný mechanismus undo/redo, musí respektovat stejné DB invarianty.

Undo nesmí obnovit neplatnou vazbu, pokud mezitím některý člen získal jiné aktivní vlastnictví.

---

# 26. Uživatelské stavy mají zůstat jednoduché

UI nemá uživatele zatěžovat umělou stavovou mašinou.

Primární uživatelský význam je:

- **Nevyřízeno**
- **Vyřízeno**

Doplňkově:

- **Skupina**
- **Automaticky**
- **Ručně**

Technické stavy jako `DISSOLVED`, `SUPERSEDED`, `IMPORT_FAILED` mohou existovat interně a v auditu, ale nemají vytvářet zbytečnou každodenní administrativu.

---

# 27. Co se nesmí stát

Následující scénáře jsou výslovně zakázané:

1. nový roční import rozpojí již hotovou skupinu;
2. identický řádek se objeví podruhé v dashboardu;
3. import přepíše starý finanční zdrojový řádek;
4. stejný PVD/PPD s jiným obsahem se tiše uloží jako druhá položka;
5. stejný terminal + SEQ s jiným obsahem se tiše uloží jako druhá položka;
6. tvrdý importní konflikt je „schován“ do karantény;
7. automatika spojí dvě různé měny;
8. automatika použije toleranci částky;
9. automatika rozbije ruční skupinu;
10. uživatel musí potvrzovat každé jednoznačné automatické párování;
11. uživatel je nucen povinně psát důvod;
12. uživatel musí nejdřív „dokončit importní dávku“;
13. skupina banka + Booking se po vytvoření znovu zobrazuje jako dva samostatné řádky;
14. objekt má v jednom pohledu jiné povolené finanční akce než v jiném pohledu;
15. CZK a EUR jsou sečteny do jednoho čísla;
16. doklad Better Hotel je považován za peněžní příjem bez skutečného finančního zdroje;
17. refresh API sám zruší finanční vazbu;
18. filtr nebo fulltext změní data.

---

# 28. Akceptační scénáře

## IMP-001 — celý rok poprvé

**Given:** databáze neobsahuje pokladní řádky.  
**When:** importuji celý roční XLS.  
**Then:** všechny nové relevantní `CARD` řádky se vloží právě jednou.

## IMP-002 — stejný roční soubor podruhé

**When:** importuji identický soubor znovu.  
**Then:** 0 nových finančních objektů.  
**And:** 0 změn existujících skupin.  
**And:** 0 změn jejich členství.

## IMP-003 — nový roční export s dalšími řádky

**Given:** leden–srpen již existuje.  
**When:** importuji leden–září.  
**Then:** leden–srpen se ignoruje jako známý obsah.  
**And:** vloží se pouze nové zářijové položky.

## IMP-004 — konflikt PVD

**Given:** `PVD123` již existuje.  
**When:** nový import obsahuje `PVD123` s jinou částkou nebo jiným kanonickým obsahem.  
**Then:** import selže před commitem.  
**And:** žádný nový řádek z tohoto importu se nevloží.

## IMP-005 — konflikt bankovní identity

Stejný `(terminal_id, seq_id)` s jiným obsahem → celý import rollback.

## IMP-006 — konflikt Booking identity

Stejná Booking source identity s odlišným finančním obsahem → celý import rollback.

## IMP-007 — žádná karanténa

Tvrdý relevantní konflikt nesmí vytvořit finanční objekt v karanténě.

## IMP-008 — import nezmění hotové párování

Opakovaný import známých řádků nesmí změnit žádné active membership ID.

---

## REC-001 — 1:1 Booking

Pokladní +50 EUR a Booking +50 EUR se stejnou jednoznačnou rezervací → skupina 0 EUR → vyřízeno.

## REC-002 — 1:1 banka

Pokladní +50 EUR a bankovní +50 EUR → skupina 0 EUR → vyřízeno.

## REC-003 — více zdrojů

Pokladní +50 EUR + banka +10 EUR + Booking +40 EUR → 0 → vyřízeno.

## REC-004 — dva pokladní proti jedné bance

Pokladní +25 +25 EUR a banka +50 EUR → 0 → vyřízeno.

## REC-005 — vnitrozdrojové Booking storno

Booking +50 EUR + Booking -50 EUR → 0 → vyřízeno bez nutnosti dokladu.

## REC-006 — testovací bankovní transakce

Banka +1 CZK + banka -1 CZK → 0 → vyřízeno.

## REC-007 — agregát před finálním párováním

Banka +10 EUR + Booking +40 EUR → vznikne nevyřízená skupina 50 EUR.  
Na dashboardu se zobrazuje jako jeden řádek.  
Po přidání pokladního +50 EUR → vyřízeno.

## REC-008 — agregát pokladny

Pokladní +25 EUR + pokladní +25 EUR → jeden nevyřízený řádek 50 EUR.  
Po přidání banky +50 EUR → vyřízeno.

## REC-009 — měnový zákaz

Pokladní 50 EUR + banka 1 250 CZK → nelze vytvořit jednu skupinu.

## REC-010 — přesná rovnost

Pokladní 50,00 EUR + Booking 49,99 EUR → zůstává rozdíl, není vyřízeno.

## REC-011 — rozpojení finální skupiny

Finální skupina složená z cashbook + podskupiny banka/Booking se rozpojí.  
Podskupina banka/Booking zůstane jako jeden nevyřízený pracovní objekt.

## REC-012 — rozložení podskupiny

Po explicitní akci Rozložit skupinu se podskupina vrátí na bankovní a Booking řádek.

---

## AUTO-001 — explicitní spuštění

Bez stisku tlačítka automatické párování nevytváří nové finanční skupiny na pozadí.

## AUTO-002 — řetězec přes doklad

Cashbook → jednoznačný doklad → rezervace → Booking reference → přesná Booking částka → auto group.

## AUTO-003 — více kandidátů

Jsou-li dva stejně vhodné protějšky, automatika neuzavře žádný.

## AUTO-004 — automatika nepoškodí ruční skupinu

Ručně seskupený člen je vyloučen z automatické spotřeby.

## AUTO-005 — opakované spuštění

Bez nových dat vytvoří druhé spuštění 0 nových skupin.

## AUTO-006 — souhrn

Po doběhu se zobrazí alespoň analyzováno / vyřízeno / zbývá.

---

## UI-001 — jeden nevyřízený seznam

Cashbook, banka, Booking i agregované skupiny jsou současně dostupné v jednom hlavním seznamu.

## UI-002 — zdrojový badge

Každý řádek jasně ukazuje původ.

## UI-003 — fulltext

Vyhledání PVD, Booking reference, SEQ ID, ARN a jména hosta funguje z jednoho vyhledávání.

## UI-004 — kombinované filtry

Filtry měna + zdroj + částka + datum + text lze kombinovat.

## UI-005 — globální akce

Tentýž objekt otevřený z fulltextu nabízí stejné finanční operace jako v dashboardu.

## UI-006 — pracovní výběr

Výběr několika objektů okamžitě ukáže součet a rekonsiliační rozdíl.

## UI-007 — více měn ve výběru

UI odděleně ukáže CZK/EUR a nepovolí společnou skupinu.

## UI-008 — bez povinného důvodu

Vytvoření ani rozpojení skupiny nevyžaduje textový komentář.

---

# 29. Migrační dopad proti současnému KájovoKarty

Aktuální program již obsahuje mnoho použitelných stavebních prvků:

- Better Hotel API klient a synchronizaci;
- Booking CSV import;
- bankovní/karetní import;
- SQLite persistence;
- ManualAllocationService;
- group/allocation model;
- reconciliation engine;
- globální action registry;
- search;
- reporting;
- saved filters;
- audit;
- backup;
- diagnostiku;
- operation manager.

Nové SSOT však vyžaduje změnit významovou osu.

## 29.1 Přidat

- nový finanční source type `CASHBOOK_CARD`;
- XLS import pokladního deníku;
- unified work object projection;
- composable/open aggregate groups;
- jednotný dashboard nevyřízeného;
- cashbook-led auto matching chain.

## 29.2 Změnit

Současný model párování je orientovaný primárně na:

`INVOICE (document side) ↔ BOOKING/CARD (source side)`

Nový model má být orientovaný primárně na:

`CASHBOOK_CARD (obligation) ↔ BANK_CARD / BOOKING (financial evidence)`

`INVOICE` a `RESERVATION` se přesunou do helper graphu.

## 29.3 Zachovat

Zachovat, pokud nejsou v konfliktu s tímto SSOT:

- lokální desktop charakter;
- SQLite;
- immutable source snapshots;
- file hash;
- atomic transactions;
- row version / concurrency checks;
- Better Hotel read-only integraci;
- centralizovaný action registry;
- fulltext;
- persistentní filtry;
- audit;
- backup a diagnostic bundle;
- undo/redo tam, kde neporušuje invariants;
- exporty.

## 29.4 Odstranit nebo přepracovat

Pro cílový finanční importní workflow odstranit koncepci, kdy:

- neznámý relevantní řádek pokračuje do karantény jako normální cesta;
- konflikt stejné přirozené identity vytváří source revision a nechává import částečně projít;
- invoice je finanční povinností namísto helperu;
- kandidát musí být uživatelem po jednom potvrzován, přestože je jednoznačný.

---

# 30. Reference na současné zdrojové implementace

Tato specifikace byla formulována s vědomím stávajících implementačních principů zejména v:

### KájovoKarty

- `src/kajovokarty/app/container.py`
- `src/kajovokarty/infrastructure/importers/bank_file.py`
- `src/kajovokarty/infrastructure/importers/booking_csv.py`
- `src/kajovokarty/infrastructure/better_hotel/`
- `src/kajovokarty/application/pairing.py`
- `src/kajovokarty/application/reconciliation.py`
- `src/kajovokarty/domain/matching.py`
- `src/kajovokarty/ui/action_registry.py`
- `src/kajovokarty/ui/main_window.py`

### KájovoVýdaje2 — převzatý princip importu pokladního deníku

- `docs/XLS_IMPORT_FORMAT.md`
- `app/integrations/xls_importer.py`

Přebírá se zejména robustní XLS parsing, hlavičkový kontrakt, normalizace, snapshot, preflight, idempotence a atomický commit.

Obchodní filtry specifické pro KájovoVýdaje2 se nepřenášejí automaticky.

---

# 31. Normativní shrnutí v jedné větě

**KájovoKarty je jednotný, ručně řízený rekonsiliační desktopový nástroj, který idempotentně sbírá karetní pokladní pohyby Better Hotel, bankovní/karetní transakce a Booking.com transakce, používá Better Hotel doklady a rezervace jako pomocný identifikační most, automaticky bez jednotlivého potvrzování uzavírá pouze jednoznačné přesné shody a veškerý zbytek umožňuje libovolně seskupovat, párovat, započítávat, rozpojovat, filtrovat a fulltextově zpracovávat v jednom společném aktuálním pracovním seznamu, vždy odděleně podle měny a bez duplicit či skrytých vedlejších účinků.**
