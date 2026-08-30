from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

BOOKING_HEADERS = [
    "Typ faktury",
    "Číslo rezervace",
    "Datum příjezdu",
    "Checkout",
    "Jméno hosta",
    "Poskytovatel platebních služeb",
    "Status rezervace",
    "Měna",
    "Status platby",
    "Částka",
    "Datum vyplacení částky ",
    "ID platby",
]

BANK_HEADERS = [
    "Typ transakce", "ID Terminálu", "ID POS", "Datum a čas vzniku", "Čas připsání na server",
    "Datum zaúčtování", "Částka", "Cashback", "Spropitné", "Měna", "ARN kód", "DCC",
    "Číslo karty/Číslo účtu", "Autoriz. kód", "Var. symbol", "Var. symbol 2", "SEQ ID",
    "Vydavatel karty", "Způsob načtení karty", "Obchodní místo", "Adresa obchodního místa",
]


def booking_rows() -> list[list[str]]:
    values = ["168,00"] * 30 + ["170,70"]
    rows: list[list[str]] = []
    for index, amount in enumerate(values, start=1):
        rows.append([
            "Rezervace",
            str(6689102800 + index),
            "29. července 2026",
            "30. července 2026",
            f"Testovací host {index}",
            "Booking.com Payments",
            "ok",
            "EUR",
            "Paid Online",
            amount,
            "30. července 2026",
            "PAYOUT-20260730",
        ])
    return rows


def bank_rows() -> list[list[object]]:
    rows: list[list[object]] = []
    for index in range(1, 46):
        amount = "2880,00" if index < 45 else "2957,50"
        rows.append(_bank_sale(index, "CZK", amount))
    for index in range(46, 65):
        amount = "100,00" if index < 64 else "116,95"
        rows.append(_bank_sale(index, "EUR", amount))
    for index in range(1, 24):
        row: list[object] = [""] * 21
        row[0] = "Uzávěrka"
        row[1] = "TERM-01"
        row[3] = f"30.07.2026 23:{index:02d}:00"
        rows.append(row)
    rows.extend([[""] * 21, [""] * 21])
    summary_count: list[object] = [""] * 21
    summary_count[0] = "Počet transakcí:"
    summary_count[6] = "87"
    rows.append(summary_count)
    summary_sum: list[object] = [""] * 21
    summary_sum[0] = "Suma částek:"
    summary_sum[6] = "131594,45"
    rows.append(summary_sum)
    assert len(rows) == 91
    return rows


def _bank_sale(index: int, currency: str, amount: str) -> list[object]:
    return [
        "Prodej",
        "TERM-01",
        "POS-01",
        f"30.07.2026 12:{index % 60:02d}:00",
        f"30.07.2026 12:{(index + 1) % 60:02d}:00",
        "30.07.2026",
        amount,
        "0,00",
        "0,00",
        currency,
        f"ARN{index:08d}",
        "0,00",
        "**** **** **** 1234",
        f"A{index:05d}",
        str(100000 + index),
        "",
        f"{index:08d}",
        "TEST BANK",
        "CHIP",
        "Hotel Chodov ASC",
        "Praha",
    ]


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, encoding in (("booking_reference.csv", "utf-8-sig"), ("booking_reference_no_bom.csv", "utf-8")):
        with (FIXTURES / name).open("w", encoding=encoding, newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(BOOKING_HEADERS)
            writer.writerows(booking_rows())
    with (FIXTURES / "bank_reference.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(BANK_HEADERS)
        writer.writerows(bank_rows())
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(BANK_HEADERS)
    for row in bank_rows():
        sheet.append(row)
    workbook.create_sheet("Návod").append(["Tento list neodpovídá importnímu schématu."])
    workbook.save(FIXTURES / "bank_reference.xlsx")
    (FIXTURES / "README.md").write_text(
        "# Syntetické referenční fixture\n\nSoubory neobsahují skutečné hosty, tokeny ani provozní data. Číselné kontrolní hodnoty odpovídají SSOT.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
