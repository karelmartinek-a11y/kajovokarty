from __future__ import annotations

import csv
from pathlib import Path

import pytest

from conftest import insert_invoice
from kajovokarty.application.audit import AuditService
from kajovokarty.application.pairing import DocumentRef, ManualAllocationService, SourceRef
from kajovokarty.domain.enums import SourceType
from kajovokarty.infrastructure.importers.booking_csv import BOOKING_HEADERS, BookingCsvImportService
from kajovokarty.infrastructure.importers.common import ImportValidationError
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


def test_corrected_booking_row_is_rejected_atomically(database: Database, tmp_path: Path) -> None:
    first_file = tmp_path / "booking-first.csv"
    corrected_file = tmp_path / "booking-corrected.csv"
    _write(first_file, "100,00")
    _write(corrected_file, "110,00")
    importer = BookingCsvImportService(database)
    first = importer.import_file(first_file)
    assert first.new_rows == 1
    old_hash = str(database.scalar("SELECT row_hash FROM booking_payment_line WHERE active_source=1"))

    with pytest.raises(ImportValidationError):
        importer.import_file(corrected_file)

    assert database.scalar("SELECT COUNT(*) FROM booking_payment_line") == 1
    assert database.scalar("SELECT active_source FROM booking_payment_line WHERE row_hash=?", (old_hash,)) == 1
    assert database.scalar("SELECT COUNT(*) FROM booking_line_revision") == 0
    assert database.scalar("SELECT COUNT(*) FROM source_revision_alert") == 0
