from kajovokarty.infrastructure.importers.bank_file import BankFileImportService
from kajovokarty.infrastructure.persistence.database import Database


def assert_report(report) -> None:
    assert report.rows_seen == 92
    assert report.sales == 64
    assert report.closures == 23
    assert report.blank_rows == 2
    assert report.summary_rows == 2
    assert report.totals_minor == {"CZK": 12967750, "EUR": 191695}


def test_bank_xlsx_schema_sheet_and_control_values(database: Database, fixture_dir) -> None:
    service = BankFileImportService(database)
    report = service.import_file(fixture_dir / "bank_reference.xlsx")
    assert_report(report)
    assert database.scalar("SELECT COUNT(*) FROM card_transaction") == 64
    assert database.scalar("SELECT COUNT(DISTINCT seq_id) FROM card_transaction") == 64
    assert database.scalar("SELECT seq_id FROM card_transaction ORDER BY seq_id LIMIT 1") == "00000001"
    assert database.scalar("SELECT authorization_code FROM card_transaction ORDER BY seq_id LIMIT 1") == "A00001"


def test_bank_csv_is_idempotent_and_summary_is_not_transaction(database: Database, fixture_dir) -> None:
    service = BankFileImportService(database)
    first = service.import_file(fixture_dir / "bank_reference.csv")
    assert_report(first)
    second = service.import_file(fixture_dir / "bank_reference.csv")
    assert second.new_rows == 0
    assert second.duplicate_rows == 64
    assert database.scalar("SELECT COALESCE(SUM(amount_minor),0) FROM card_transaction WHERE currency_code='CZK'") == 12967750
    assert database.scalar("SELECT COALESCE(SUM(amount_minor),0) FROM card_transaction WHERE currency_code='EUR'") == 191695
