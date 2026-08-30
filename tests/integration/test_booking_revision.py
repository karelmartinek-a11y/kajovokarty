from __future__ import annotations

import csv
from pathlib import Path

from conftest import insert_invoice
from kajovokarty.application.audit import AuditService
from kajovokarty.application.pairing import DocumentRef, ManualAllocationService, SourceRef
from kajovokarty.domain.enums import SourceType
from kajovokarty.infrastructure.importers.booking_csv import BOOKING_HEADERS, BookingCsvImportService
from kajovokarty.infrastructure.persistence.database import Database


def _write(path: Path, amount: str) -> None:
    row = {
        "Typ faktury": "Rezervace",
        "Číslo rezervace": "6689102875",
        "Datum příjezdu": "29. července 2026",
        "Checkout": "30. července 2026",
        "Jméno hosta": "Test Host",
        "Poskytovatel platebních služeb": "Booking.com",
        "Status rezervace": "ok",
        "Měna": "EUR",
        "Status platby": "Paid Online",
        "Částka": amount,
        "Datum vyplacení částky": "30. července 2026",
        "ID platby": "PAYOUT-1",
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BOOKING_HEADERS)
        writer.writeheader()
        writer.writerow(row)


def test_corrected_booking_row_preserves_history_and_requires_review(database: Database, tmp_path: Path) -> None:
    first_file = tmp_path / "booking-first.csv"
    corrected_file = tmp_path / "booking-corrected.csv"
    _write(first_file, "100,00")
    _write(corrected_file, "110,00")
    importer = BookingCsvImportService(database)
    first = importer.import_file(first_file)
    assert first.new_rows == 1
    old_hash = str(database.scalar("SELECT row_hash FROM booking_payment_line WHERE active_source=1"))

    insert_invoice(database, "i1", "FA1", 10_000, currency="EUR")
    pairing = ManualAllocationService(database, AuditService())
    group_id, _ = pairing.pair_one(DocumentRef("i1"), SourceRef(SourceType.BOOKING, old_hash))

    corrected = importer.import_file(corrected_file)
    assert corrected.new_rows == 1
    assert corrected.conflicts == 1
    assert database.scalar("SELECT COUNT(*) FROM booking_payment_line") == 2
    assert database.scalar("SELECT active_source FROM booking_payment_line WHERE row_hash=?", (old_hash,)) == 0
    assert database.scalar("SELECT status FROM booking_payment_line WHERE row_hash=?", (old_hash,)) == "REVIEW_REQUIRED"
    assert database.scalar("SELECT COUNT(*) FROM booking_line_revision") == 1
    assert database.scalar("SELECT COUNT(*) FROM source_revision_alert WHERE state='OPEN'") == 1
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "REVIEW_REQUIRED"
