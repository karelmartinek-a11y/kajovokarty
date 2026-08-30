from __future__ import annotations

import csv
from pathlib import Path

from kajovokarty.application.audit import AuditService
from kajovokarty.application.quarantine import QuarantineService
from kajovokarty.infrastructure.importers.bank_file import BANK_HEADERS, BankFileImportService
from kajovokarty.infrastructure.importers.booking_csv import BOOKING_HEADERS, BookingCsvImportService
from kajovokarty.infrastructure.persistence.database import Database


def _write_booking(path: Path, payment_status: str = "Neznámá platba") -> None:
    values = {
        "Typ faktury": "Rezervace",
        "Číslo rezervace": "6689102875",
        "Datum příjezdu": "29. července 2026",
        "Checkout": "30. července 2026",
        "Jméno hosta": "Test Host",
        "Poskytovatel platebních služeb": "Booking.com",
        "Status rezervace": "ok",
        "Měna": "EUR",
        "Status platby": payment_status,
        "Částka": "100,00",
        "Datum vyplacení částky": "30. července 2026",
        "ID platby": "PAYOUT-1",
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BOOKING_HEADERS)
        writer.writeheader()
        writer.writerow(values)


def _write_unknown_bank(path: Path, fixture_dir: Path) -> None:
    with (fixture_dir / "bank_reference.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        source = next(row for row in reader if row["Typ transakce"] == "Prodej")
    source["Typ transakce"] = "Nový typ"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BANK_HEADERS)
        writer.writeheader()
        writer.writerow(source)


def _service(database: Database) -> tuple[QuarantineService, BookingCsvImportService, BankFileImportService]:
    booking = BookingCsvImportService(database)
    bank = BankFileImportService(database)
    return QuarantineService(database, AuditService(), booking, bank), booking, bank


def test_booking_mapping_reprocesses_quarantined_row(database: Database, tmp_path: Path) -> None:
    service, booking, _ = _service(database)
    path = tmp_path / "unknown_booking.csv"
    _write_booking(path)
    report = booking.import_file(path)
    assert report.quarantined == 1
    quarantine_id = str(database.scalar("SELECT id FROM quarantined_source_row WHERE run_type='BOOKING'"))

    command_id = service.map_value(quarantine_id, "payment_status", "PAID ONLINE")
    result = service.retry(quarantine_id)
    assert result.new_rows == 1
    assert database.scalar("SELECT state FROM quarantined_source_row WHERE id=?", (quarantine_id,)) == "RESOLVED"
    assert database.scalar("SELECT COUNT(*) FROM booking_payment_line") == 1
    service.undo(command_id)
    assert database.scalar("SELECT COUNT(*) FROM import_value_mapping") == 0
    service.redo(command_id)
    assert database.scalar("SELECT mapped_meaning FROM import_value_mapping") == "PAID ONLINE"


def test_quarantine_ignore_is_audited_and_reversible(database: Database, tmp_path: Path) -> None:
    service, booking, _ = _service(database)
    path = tmp_path / "unknown_booking.csv"
    _write_booking(path)
    booking.import_file(path)
    quarantine_id = str(database.scalar("SELECT id FROM quarantined_source_row"))
    command_id = service.ignore(quarantine_id, "nerelevantní")
    assert database.scalar("SELECT state FROM quarantined_source_row WHERE id=?", (quarantine_id,)) == "IGNORED"
    service.undo(command_id)
    assert database.scalar("SELECT state FROM quarantined_source_row WHERE id=?", (quarantine_id,)) == "OPEN"
    service.redo(command_id)
    assert database.scalar("SELECT state FROM quarantined_source_row WHERE id=?", (quarantine_id,)) == "IGNORED"


def test_bank_mapping_reprocesses_unknown_transaction(database: Database, fixture_dir: Path, tmp_path: Path) -> None:
    service, _, bank = _service(database)
    path = tmp_path / "unknown_bank.csv"
    _write_unknown_bank(path, fixture_dir)
    report = bank.import_file(path)
    assert report.quarantined == 1
    quarantine_id = str(database.scalar("SELECT id FROM quarantined_source_row WHERE run_type='BANK'"))
    service.map_value(quarantine_id, "transaction_type", "SALE")
    result = service.retry(quarantine_id)
    assert result.new_rows == 1
    assert database.scalar("SELECT COUNT(*) FROM card_transaction") == 1
