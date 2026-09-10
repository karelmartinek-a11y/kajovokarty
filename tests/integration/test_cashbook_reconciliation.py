from pathlib import Path

import pytest

from kajovokarty.application.audit import AuditService
from kajovokarty.application.pairing import ManualAllocationService, PairingError, SourceRef
from kajovokarty.domain.enums import SourceType
from kajovokarty.infrastructure.importers.cashbook_xls import CashbookFileImportService


HEADER = "Vystaveno,Pohyb,Číslo,Označení,Klient,Příjem,Výdaj,Stav pokladny,Měna,Forma úhrady,Pokladna,Variabilní symbol,Vystavil\n"


def _cashbook(path: Path, amount: str = "50.00", receipt: str = "PVD123") -> None:
    path.write_text(
        HEADER
        + f"30.07.2026 10:00,Příjem,{receipt},Ubytování,Host,{amount},0,50,EUR,Karta,Recepce,VS1,Admin\n"
        + "30.07.2026 10:01,Příjem,OPEN,Počáteční stav,,0,0,0,EUR,Karta,Recepce,,Admin\n"
        + "30.07.2026 10:02,Příjem,CASH,Poplatek,,10,0,10,EUR,Hotovost,Recepce,,Admin\n",
        encoding="utf-8",
    )


def test_cashbook_import_is_idempotent_and_ignores_non_card_rows(database, tmp_path) -> None:
    path = tmp_path / "cashbook.csv"
    _cashbook(path)
    service = CashbookFileImportService(database)
    first = service.import_file(path)
    second = service.import_file(path)
    assert first.new_rows == 1
    assert first.ignored_rows == 2
    assert second.new_rows == 0
    assert second.duplicate_rows == 1
    assert database.scalar("SELECT COUNT(*) FROM cashbook_card_transaction") == 1


def test_cashbook_conflict_rolls_back_whole_import(database, tmp_path) -> None:
    path = tmp_path / "cashbook.csv"
    _cashbook(path)
    service = CashbookFileImportService(database)
    service.import_file(path)
    _cashbook(path, amount="51.00", receipt="PVD123")
    with pytest.raises(ValueError):
        service.import_file(path)
    assert database.scalar("SELECT COUNT(*) FROM cashbook_card_transaction") == 1
    assert database.scalar("SELECT COUNT(*) FROM quarantined_source_row WHERE run_type='CASHBOOK'") == 0


def test_source_groups_reconcile_cashbook_bank_and_booking(database) -> None:
    now = "2026-07-31T10:00:00Z"
    database.execute(
        "INSERT INTO cashbook_card_transaction(id,cashbook_identity,occurred_at,direction,amount_minor,currency_code,receipt_number,label,payment_form,status,raw_json,content_hash,first_seen_utc,last_seen_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("cash1", "PVD123", now, "INCOME", 5000, "EUR", "PVD123", "Ubytování", "Karta", "UNMATCHED", "{}", "cash1", now, now),
    )
    database.execute(
        "INSERT INTO card_transaction(id,terminal_id,seq_id,transaction_type,occurred_at,posted_date,amount_minor,currency_code,status,raw_json,content_hash,first_seen_utc,last_seen_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
        ("card1", "T", "1", "Prodej", now, "2026-07-31", 1000, "EUR", "UNMATCHED", "{}", "card1", now, now),
    )
    database.execute(
        "INSERT INTO booking_payout_batch(id,natural_key,payment_id,payout_date,currency_code,content_hash,first_seen_utc,last_seen_utc) VALUES(?,?,?,?,?,?,?,?)",
        ("batch1", "batch1", "pay1", "2026-07-31", "EUR", "batch1", now, now),
    )
    database.execute(
        "INSERT INTO booking_payment_line(row_hash,batch_id,booking_reference,amount_minor,currency_code,reservation_status,payment_status,status,raw_json,content_hash,first_seen_utc,last_seen_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        ("book1", "batch1", "B1", 4000, "EUR", "OK", "PAID", "UNMATCHED", "{}", "book1", now, now),
    )
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.pair_sources([SourceRef(SourceType.CARD, "card1"), SourceRef(SourceType.BOOKING, "book1")])
    assert database.scalar("SELECT difference_minor FROM match_group WHERE id=?", (group_id,)) == -5000
    service.add_sources_to_group(group_id, [SourceRef(SourceType.CASHBOOK_CARD, "cash1")])
    assert database.scalar("SELECT difference_minor FROM match_group WHERE id=?", (group_id,)) == 0
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "AGGREGATE_MATCHED"


def test_source_group_rejects_mixed_currency(database) -> None:
    now = "2026-07-31T10:00:00Z"
    database.execute("INSERT INTO cashbook_card_transaction(id,cashbook_identity,occurred_at,direction,amount_minor,currency_code,receipt_number,label,payment_form,status,raw_json,content_hash,first_seen_utc,last_seen_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("czk", "PVD-CZK", now, "INCOME", 5000, "CZK", "PVD-CZK", "x", "Karta", "UNMATCHED", "{}", "czk", now, now))
    database.execute("INSERT INTO card_transaction(id,terminal_id,seq_id,transaction_type,occurred_at,posted_date,amount_minor,currency_code,status,raw_json,content_hash,first_seen_utc,last_seen_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)", ("eur", "T", "2", "Prodej", now, "2026-07-31", 5000, "EUR", "UNMATCHED", "{}", "eur", now, now))
    with pytest.raises(PairingError):
        ManualAllocationService(database, AuditService()).pair_sources([SourceRef(SourceType.CASHBOOK_CARD, "czk"), SourceRef(SourceType.CARD, "eur")])


def test_groups_are_composable_and_can_be_detached_or_dissolved(database) -> None:
    now = "2026-07-31T10:00:00Z"
    for identifier, terminal, seq, amount in (("c1", "T", "1", 1000), ("c2", "T", "2", 4000)):
        database.execute("INSERT INTO card_transaction(id,terminal_id,seq_id,transaction_type,occurred_at,posted_date,amount_minor,currency_code,status,raw_json,content_hash,first_seen_utc,last_seen_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)", (identifier, terminal, seq, "Prodej", now, "2026-07-31", amount, "EUR", "UNMATCHED", "{}", identifier, now, now))
    service = ManualAllocationService(database, AuditService())
    child, _ = service.pair_sources([SourceRef(SourceType.CARD, "c1")])
    parent, _ = service.pair_sources([SourceRef(SourceType.CARD, "c2")])
    service.add_group_to_group(parent, child)
    assert database.scalar("SELECT difference_minor FROM match_group WHERE id=?", (parent,)) == -5000
    service.detach_group_parent(parent, child)
    assert database.scalar("SELECT active FROM match_group_child WHERE parent_group_id=? AND child_group_id=?", (parent, child)) == 0
    service.dissolve_group(child)
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (child,)) == "REVERSED"
