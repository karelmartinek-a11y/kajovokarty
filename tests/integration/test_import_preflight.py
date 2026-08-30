from __future__ import annotations

from pathlib import Path

import pytest

from kajovokarty.application.import_preflight import ImportPreflightError, ImportPreflightService
from kajovokarty.infrastructure.importers.bank_file import BankFileImportService
from kajovokarty.infrastructure.importers.booking_csv import BookingCsvImportService


def test_booking_preflight_reports_hash_schema_and_rows(database):
    service = ImportPreflightService(
        database,
        BookingCsvImportService(database),
        BankFileImportService(database),
    )
    preview = service.booking_preview(Path("tests/fixtures/booking_reference.csv"), max_megabytes=10)
    assert preview.schema_columns == 12
    assert preview.estimated_rows == 31
    assert preview.usable_rows == 31
    assert preview.quarantine_rows == 0
    assert preview.currencies == ("EUR",)
    assert len(preview.sha256) == 64
    assert "SHA-256" in preview.human_summary


def test_bank_preflight_reports_reference_fixture(database):
    service = ImportPreflightService(
        database,
        BookingCsvImportService(database),
        BankFileImportService(database),
    )
    preview = service.bank_preview(Path("tests/fixtures/bank_reference.xlsx"), max_megabytes=10)
    assert preview.schema_columns == 21
    assert preview.usable_rows == 64
    assert preview.quarantine_rows == 0
    assert preview.currencies == ("CZK", "EUR")
    assert preview.selected_sheet


def test_preflight_rejects_empty_or_oversized_file(database, tmp_path):
    service = ImportPreflightService(
        database,
        BookingCsvImportService(database),
        BankFileImportService(database),
    )
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    with pytest.raises(ImportPreflightError):
        service.booking_preview(empty, max_megabytes=1)

    oversized = tmp_path / "too-large.csv"
    oversized.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ImportPreflightError):
        service.booking_preview(oversized, max_megabytes=1)
