from __future__ import annotations

import json
from uuid import uuid4

import pytest

from conftest import insert_card, insert_invoice
from kajovokarty.application.audit import AuditService
from kajovokarty.application.pairing import DocumentRef, ManualAllocationService, PairingError, SourceRef
from kajovokarty.domain.enums import SourceType
from kajovokarty.infrastructure.importers.common import utc_now
from kajovokarty.infrastructure.persistence.database import Database


def test_remove_allocation_recalculates_partial_and_undo_restores(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 10_000)
    insert_card(database, "c1", "T1", "0001", 10_000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.pair_one(DocumentRef("i1"), SourceRef(SourceType.CARD, "c1"))
    allocation_id = str(database.scalar("SELECT id FROM allocation WHERE group_id=?", (group_id,)))

    command_id = service.remove_allocation(allocation_id)
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "UNMATCHED"
    assert database.scalar("SELECT active FROM allocation WHERE id=?", (allocation_id,)) == 0

    service.undo(command_id)
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "MANUAL_MATCHED"
    assert database.scalar("SELECT active FROM allocation WHERE id=?", (allocation_id,)) == 1
    service.redo(command_id)
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "UNMATCHED"


def test_manual_cash_has_real_allocation_and_compensating_undo_redo(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 10_000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.create_invoice_case("i1")
    settlement_id, command_id = service.add_manual_settlement(group_id, SourceType.CASH, 10_000)

    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE source_type='CASH' AND source_id=? AND active=1", (settlement_id,)) == 1
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "MANUAL_MATCHED"
    service.undo(command_id)
    assert database.scalar("SELECT active FROM manual_settlement WHERE id=?", (settlement_id,)) == 0
    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE source_id=? AND active=1", (settlement_id,)) == 0
    service.redo(command_id)
    assert database.scalar("SELECT active FROM manual_settlement WHERE id=?", (settlement_id,)) == 1
    assert database.scalar("SELECT COUNT(*) FROM allocation WHERE source_id=? AND active=1", (settlement_id,)) == 1


def test_manual_resolution_reopen_and_undo_restore_lock_and_state(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 10_000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.create_invoice_case("i1")

    resolve_command = service.manual_resolve(group_id)
    assert tuple(database.query("SELECT status,manual_lock FROM match_group WHERE id=?", (group_id,))[0]) == ("MANUAL_RESOLVED", 1)
    service.undo(resolve_command)
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "UNDERPAID"
    service.redo(resolve_command)
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "MANUAL_RESOLVED"

    reopen_command = service.reopen_manual_resolution(group_id)
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "UNDERPAID"
    service.undo(reopen_command)
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "MANUAL_RESOLVED"
    service.redo(reopen_command)
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "UNDERPAID"


def test_manual_lock_blocks_second_group(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 10_000)
    insert_card(database, "c1", "T1", "0001", 10_000)
    service = ManualAllocationService(database, AuditService())
    service.pair_one(DocumentRef("i1"), SourceRef(SourceType.CARD, "c1"))
    with pytest.raises(PairingError, match="chrání ruční rozhodnutí"):
        service.pair_one(DocumentRef("i1"), SourceRef(SourceType.CARD, "c1"))


def test_revalidate_group_resolves_alert_and_is_reversible(database: Database) -> None:
    insert_invoice(database, "i1", "FA1", 10_000)
    insert_card(database, "c1", "T1", "0001", 10_000)
    service = ManualAllocationService(database, AuditService())
    group_id, _ = service.pair_one(DocumentRef("i1"), SourceRef(SourceType.CARD, "c1"))
    alert_id = uuid4().hex
    database.execute(
        "INSERT INTO source_revision_alert(id,object_ref,previous_hash,current_hash,changed_fields_json,affected_group_ids_json,state,detected_at_utc) VALUES(?,?,?,?,?,?,?,?)",
        (alert_id, "CARD:c1", "old", "new", json.dumps(["amount_minor"]), json.dumps([group_id]), "OPEN", utc_now()),
    )
    database.execute("UPDATE match_group SET status='REVIEW_REQUIRED',review_required_reason='Zdrojová data se změnila' WHERE id=?", (group_id,))

    command_id = service.revalidate_group(group_id)
    assert database.scalar("SELECT state FROM source_revision_alert WHERE id=?", (alert_id,)) == "RESOLVED"
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "MANUAL_MATCHED"
    service.undo(command_id)
    assert database.scalar("SELECT state FROM source_revision_alert WHERE id=?", (alert_id,)) == "OPEN"
    assert database.scalar("SELECT status FROM match_group WHERE id=?", (group_id,)) == "REVIEW_REQUIRED"
    service.redo(command_id)
    assert database.scalar("SELECT state FROM source_revision_alert WHERE id=?", (alert_id,)) == "RESOLVED"
