# Pravidla úhrad

## Zdroje

- Booking.com import je potvrzení úhrady a identifikuje se `booking_reference`.
- Terminálový import je potvrzení úhrady a identifikuje se `card_transaction.id`/SEQ.
- Better Hotel poskytuje daňové doklady. Do přehledu dokladů s úhradou kartou patří pouze `pay_method=2` s vyplněným `paid` nebo `payed`.

## Dokladová částka a stavy

U dokladu s úhradou kartou se jako částka k úhradě používá `invoice.total`.
Uživatelské stavy jsou pouze:

- `NEUHRAZEN`: není aktivně uhrazena žádná částka,
- `ČÁSTEČNÁ ÚHRADA`: aktivně je uhrazena jen část částky,
- `UHRAZEN`: je uhrazena celá částka nebo je doklad ručně označen bez důkazu.

Chybějící Booking číslo není chyba ani konflikt; doklad je pouze dostupný pro ruční párování a filtr „bez čísla“.
Stejné Booking číslo může být u více dokladů.

## Párování

Automatické párování:

1. hledá volné Booking potvrzení se stejným číslem rezervace zdroje, měnou a dostatečným zůstatkem,
2. pokud takové potvrzení není k dispozici, hledá terminálové potvrzení ve stejné měně, stejné částce a v intervalu 0–2 kalendářní dny,
3. potvrzení může být rozděleno mezi více dokladů, ale nikdy nad jeho celkovou částku,
4. ruční částečné uhrazení dokladu není dovoleno; ručně lze použít pouze potvrzení s dostatečným zůstatkem,
5. ruční označení bez důkazu nespotřebuje žádné potvrzení a lze ho kdykoli zrušit.

Každé použití a rozpojení potvrzení zůstává v auditní historii. Zdrojová věta importu je u Booking.com i terminálu uložena v plném `raw_json`.
