from __future__ import annotations

import pytest

from conftest import insert_card, insert_invoice
from kajovokarty.application.audit import AuditService
from kajovokarty.application.pairing import DocumentRef, ManualAllocationService, PairingError, SourceRef
from kajovokarty.domain.enums import SourceType
from kajovokarty.infrastructure.persistence.database import Database


def test_add_members_to_existing_group_is_atomic_audited_and_reversible(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 5_000)
    insert_card(database, "c1", "T1", "0001", 5_000)
    insert_invoice(database, "i2", "FA2", 3_000)
    insert_card(database, "c2", "T1", "0002", 3_000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.pair_one(DocumentRef("i1"), SourceRef(SourceType.CARD, "c1"))

    additions = [DocumentRef("i2")]
    sources = [SourceRef(SourceType.CARD, "c2")]
    plan = service.propose_group_additions(group_id, additions, sources)
    command_id = service.add_to_group(
        group_id,
        additions,
        sources,
        allocations=plan,
    )

    group = database.query("SELECT * FROM match_group WHERE id=?", (group_id,))[0]
    assert group["document_total_minor"] == 8_000
    assert group["source_total_minor"] == 8_000
    assert group["difference_minor"] == 0
    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE group_id=? AND active=1", (group_id,)) == 2
    assert database.scalar("SELECT COUNT(*) FROM audit_event WHERE event_code='GROUP_MEMBERS_ADDED'") == 1

    service.undo(command_id)
    group = database.query("SELECT * FROM match_group WHERE id=?", (group_id,))[0]
    assert group["document_total_minor"] == 5_000
    assert group["source_total_minor"] == 5_000
    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE group_id=? AND active=1", (group_id,)) == 1

    service.redo(command_id)
    group = database.query("SELECT * FROM match_group WHERE id=?", (group_id,))[0]
    assert group["document_total_minor"] == 8_000
    assert group["source_total_minor"] == 8_000
    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE group_id=? AND active=1", (group_id,)) == 2


def test_add_document_only_recalculates_existing_group_without_fictitious_source(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 5_000)
    insert_card(database, "c1", "T1", "0001", 5_000)
    insert_invoice(database, "i2", "FA2", 3_000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.pair_one(DocumentRef("i1"), SourceRef(SourceType.CARD, "c1"))

    service.add_to_group(group_id, [DocumentRef("i2")], [])

    group = database.query("SELECT * FROM match_group WHERE id=?", (group_id,))[0]
    assert group["document_total_minor"] == 8_000
    assert group["source_total_minor"] == 5_000
    assert group["difference_minor"] == 3_000
    assert group["status"] == "PARTIAL"
    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE group_id=? AND active=1", (group_id,)) == 1


def test_add_members_without_explicit_plan_never_creates_pairwise_allocations(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 5_000)
    insert_card(database, "c1", "T1", "0001", 5_000)
    insert_invoice(database, "i2", "FA2", 3_000)
    insert_card(database, "c2", "T1", "0002", 3_000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.pair_one(DocumentRef("i1"), SourceRef(SourceType.CARD, "c1"))

    service.add_to_group(
        group_id,
        [DocumentRef("i2")],
        [SourceRef(SourceType.CARD, "c2")],
    )

    assert database.scalar(
        "SELECT COUNT(*) FROM allocation WHERE group_id=? AND active=1", (group_id,)
    ) == 1
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "PARTIAL"


def test_aggregate_group_rejects_pairwise_member_drop(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 5_000)
    insert_card(database, "c1", "T1", "0001", 5_000)
    insert_invoice(database, "i2", "FA2", 3_000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.pair(
        [DocumentRef("i1")],
        [SourceRef(SourceType.CARD, "c1")],
        aggregate=True,
    )

    with pytest.raises(PairingError, match="detailní rozpis"):
        service.add_to_group(group_id, [DocumentRef("i2")], [])


def test_review_required_case_can_be_consciously_reopened_and_undone(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 5_000)
    insert_card(database, "c1", "T1", "0001", 5_000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.pair_one(DocumentRef("i1"), SourceRef(SourceType.CARD, "c1"))
    with database.transaction() as conn:
        conn.execute(
            "UPDATE match_group SET status='REVIEW_REQUIRED',review_required_reason='amount_minor' WHERE id=?",
            (group_id,),
        )
        conn.execute(
            "INSERT INTO source_revision_alert(id,object_ref,previous_hash,current_hash,changed_fields_json,"
            "affected_group_ids_json,state,detected_at_utc) VALUES(?,?,?,?,?,?,?,?)",
            (
                "alert1",
                "CARD:c1",
                "old",
                "new",
                '["amount_minor"]',
                f'["{group_id}"]',
                "OPEN",
                "2026-07-31T12:00:00Z",
            ),
        )

    command_id = service.reopen_review_required(group_id)
    assert database.scalar("SELECT state FROM source_revision_alert WHERE id='alert1'") == "RESOLVED"
    assert database.scalar("SELECT resolution_method FROM source_revision_alert WHERE id='alert1'") == "REOPENED"
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) != "REVIEW_REQUIRED"

    service.undo(command_id)
    assert database.scalar("SELECT state FROM source_revision_alert WHERE id='alert1'") == "OPEN"
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "REVIEW_REQUIRED"
