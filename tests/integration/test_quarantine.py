from __future__ import annotations

import csv
from pathlib import Path

import pytest

from kajovokarty.application.audit import AuditService
from kajovokarty.application.quarantine import QuarantineService
from kajovokarty.infrastructure.importers.bank_file import BANK_HEADERS, BankFileImportService
from kajovokarty.infrastructure.importers.booking_csv import BOOKING_HEADERS, BookingCsvImportService
from kajovokarty.infrastructure.importers.common import ImportValidationError
from kajovokarty.infrastructure.persistence.database import Database


def _write_booking(path: Path, payment_status: str = "Unknown payment") -> None:
    values = dict(zip(BOOKING_HEADERS, [
        "Reservation", "6689102875", "2026-07-29", "2026-07-30", "Test Host",
        "Booking.com", "ok", "EUR", payment_status, "100,00", "2026-07-30", "PAYOUT-1",
    ]))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BOOKING_HEADERS)
        writer.writeheader()
        writer.writerow(values)


def _write_unknown_bank(path: Path, fixture_dir: Path) -> None:
    with (fixture_dir / "bank_reference.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        source = next(row for row in reader if row["Typ transakce"] == "Prodej")
    source["Typ transakce"] = "Unknown type"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BANK_HEADERS)
        writer.writeheader()
        writer.writerow(source)


def _service(database: Database) -> tuple[QuarantineService, BookingCsvImportService, BankFileImportService]:
    booking = BookingCsvImportService(database)
    bank = BankFileImportService(database)
    return QuarantineService(database, AuditService(), booking, bank), booking, bank


def test_booking_unknown_status_fails_atomically_without_quarantine(database: Database, tmp_path: Path) -> None:
    _, booking, _ = _service(database)
    path = tmp_path / "unknown_booking.csv"
    _write_booking(path)
    with pytest.raises(ImportValidationError):
        booking.import_file(path)
    assert database.scalar("SELECT COUNT(*) FROM quarantined_source_row") == 0
    assert database.scalar("SELECT COUNT(*) FROM booking_payment_line") == 0


def test_bank_unknown_transaction_fails_atomically_without_quarantine(database: Database, fixture_dir: Path, tmp_path: Path) -> None:
    _, _, bank = _service(database)
    path = tmp_path / "unknown_bank.csv"
    _write_unknown_bank(path, fixture_dir)
    with pytest.raises(ImportValidationError):
        bank.import_file(path)
    assert database.scalar("SELECT COUNT(*) FROM quarantined_source_row") == 0
    assert database.scalar("SELECT COUNT(*) FROM card_transaction") == 0
