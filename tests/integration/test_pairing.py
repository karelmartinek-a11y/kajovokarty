from kajovokarty.application.audit import AuditService
from kajovokarty.application.pairing import DocumentRef, ManualAllocationService, PairingError, SourceRef
from kajovokarty.domain.enums import SourceType
from kajovokarty.infrastructure.persistence.database import Database
from conftest import insert_card, insert_invoice


def test_one_to_one_pair_and_compensating_undo_redo(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 10000)
    insert_card(database, "c1", "T1", "0001", 10000)
    service = ManualAllocationService(database, AuditService())
    group_id, command_id = service.pair_one(DocumentRef("i1"), SourceRef(SourceType.CARD, "c1"))
    group = database.query("SELECT * FROM match_group WHERE id=?", (group_id,))[0]
    assert group["difference_minor"] == 0
    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE active=1") == 1
    service.undo(command_id)
    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE active=1") == 0
    assert database.scalar("SELECT COUNT(*) FROM audit_event WHERE event_code='COMMAND_UNDO'") == 1
    service.redo(command_id)
    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE active=1") == 1
    assert database.scalar("SELECT COUNT(*) FROM audit_event WHERE event_code='COMMAND_REDO'") == 1


def test_one_to_many_and_remaining_amounts(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 15000)
    insert_card(database, "c1", "T1", "0001", 10000)
    insert_card(database, "c2", "T1", "0002", 5000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.pair([DocumentRef("i1")], [SourceRef(SourceType.CARD, "c1"), SourceRef(SourceType.CARD, "c2")])
    assert database.scalar("SELECT SUM(amount_minor) FROM allocation WHERE group_id=? AND active=1", (group_id,)) == 15000
    assert database.scalar("SELECT difference_minor FROM match_group WHERE id=?", (group_id,)) == 0


def test_aggregate_group_has_no_fictitious_allocations(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 10000)
    insert_invoice(database, "i2", "FA2", 5000)
    insert_card(database, "c1", "T1", "0001", 8000)
    insert_card(database, "c2", "T1", "0002", 7000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.pair([DocumentRef("i1"), DocumentRef("i2")], [SourceRef(SourceType.CARD, "c1"), SourceRef(SourceType.CARD, "c2")], aggregate=True)
    assert database.scalar("SELECT allocation_mode FROM match_group WHERE id=?", (group_id,)) == "AGGREGATE"
    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE group_id=?", (group_id,)) == 0


def test_many_to_many_requires_explicit_reviewed_plan(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 10_000)
    insert_invoice(database, "i2", "FA2", 5_000)
    insert_card(database, "c1", "T1", "0001", 8_000)
    insert_card(database, "c2", "T1", "0002", 7_000)
    service = ManualAllocationService(database, AuditService())
    documents = [DocumentRef("i1"), DocumentRef("i2")]
    sources = [SourceRef(SourceType.CARD, "c1"), SourceRef(SourceType.CARD, "c2")]

    try:
        service.pair(documents, sources)
    except PairingError as exc:
        assert "výslovně potvrzený detailní rozpis" in str(exc)
    else:
        raise AssertionError("N:M nesmí tiše vytvořit libovolné párové vazby")

    plan = service.propose_allocations(documents, sources)
    assert [(invoice_id, ref.object_ref, amount) for invoice_id, ref, amount in plan] == [
        ("i1", "CARD:c1", 8_000),
        ("i1", "CARD:c2", 2_000),
        ("i2", "CARD:c2", 5_000),
    ]
    group_id, _ = service.pair(documents, sources, allocations=plan)
    assert database.scalar(
        "SELECT COUNT(*) FROM allocation WHERE group_id=? AND active=1", (group_id,)
    ) == 3


def test_different_currency_is_rejected(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 10000, "CZK")
    insert_card(database, "c1", "T1", "0001", 10000, "EUR")
    service = ManualAllocationService(database, AuditService())
    try:
        service.pair_one(DocumentRef("i1"), SourceRef(SourceType.CARD, "c1"))
    except PairingError as exc:
        assert "různé měny" in str(exc) or "zdroj je v EUR" in str(exc)
    else:
        raise AssertionError("Rozdílné měny nesmějí vytvořit vazbu")


def test_manual_cash_and_manual_resolution_are_audited(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 10000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.create_invoice_case("i1")
    service.add_manual_settlement(group_id, SourceType.CASH, 10000, note="převzato na recepci")
    assert database.scalar("SELECT difference_minor FROM match_group WHERE id=?", (group_id,)) == 0
    service.manual_resolve(group_id)
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "MANUAL_RESOLVED"
    assert database.scalar("SELECT COUNT(*) FROM audit_event WHERE object_ref LIKE 'MANUAL:%'") == 1


def test_multiselect_drop_preview_accepts_exact_many_to_one(database: Database) -> None:
    from kajovokarty.application.pairing import PairingDropValidationService

    insert_invoice(database, "i1", "FA1", 6_000)
    insert_invoice(database, "i2", "FA2", 4_000)
    insert_card(database, "c1", "T1", "0001", 10_000)
    preview = PairingDropValidationService(database).preview_many(
        [DocumentRef("i1"), DocumentRef("i2")],
        [SourceRef(SourceType.CARD, "c1")],
    )
    assert preview.allowed is True
    assert preview.exact is True
    assert preview.assign_minor == 10_000
    assert preview.document_remaining_minor == 10_000
    assert preview.source_remaining_minor == 10_000


def test_multiselect_drop_preview_rejects_mixed_currency(database: Database) -> None:
    from kajovokarty.application.pairing import PairingDropValidationService

    insert_invoice(database, "i1", "FA1", 6_000, "CZK")
    insert_invoice(database, "i2", "FA2", 4_000, "EUR")
    insert_card(database, "c1", "T1", "0001", 10_000, "CZK")
    preview = PairingDropValidationService(database).preview_many(
        [DocumentRef("i1"), DocumentRef("i2")],
        [SourceRef(SourceType.CARD, "c1")],
    )
    assert preview.allowed is False
    assert "různé měny" in preview.reason
