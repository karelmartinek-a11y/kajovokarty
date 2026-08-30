from kajovokarty.infrastructure.importers.booking_csv import BookingCsvImportService
from kajovokarty.infrastructure.persistence.database import Database


def test_booking_reference_fixture_bom_and_idempotence(database: Database, fixture_dir) -> None:
    service = BookingCsvImportService(database)
    report = service.import_file(fixture_dir / "booking_reference.csv")
    assert report.rows_seen == 31
    assert report.new_rows == 31
    assert report.totals_minor == {"EUR": 521070}
    assert database.scalar("SELECT COUNT(DISTINCT booking_reference) FROM booking_payment_line") == 31
    assert database.scalar("SELECT COUNT(*) FROM booking_payout_batch") == 1
    duplicate = service.import_file(fixture_dir / "booking_reference.csv")
    assert duplicate.new_rows == 0
    assert duplicate.duplicate_rows == 31


def test_booking_without_bom_and_reordered_headers(database: Database, fixture_dir, tmp_path) -> None:
    service = BookingCsvImportService(database)
    parsed = service.inspect(fixture_dir / "booking_reference_no_bom.csv")
    assert len(parsed) == 31
    assert sum(row.line.amount_minor for row in parsed) == 521070
