import pytest

from conftest import insert_card, insert_invoice
from kajovokarty.application.audit import AuditService
from kajovokarty.application.pairing import ManualAllocationService
from kajovokarty.application.reconciliation import ReconciliationCancelled, ReconciliationService
from kajovokarty.domain.matching import MatchingSettings


def test_reconciliation_can_cancel_without_partial_candidate_commit(database) -> None:
    insert_invoice(database, "i1", "FA1", 10_000)
    insert_card(database, "c1", "T1", "0001", 10_000)
    service = ReconciliationService(database, ManualAllocationService(database, AuditService()))
    state = {"cancel": False}

    def progress(current: int, total: int, message: str) -> None:
        assert total >= 1
        if "Generuji" in message:
            state["cancel"] = True

    with pytest.raises(ReconciliationCancelled):
        service.recompute(
            MatchingSettings(),
            cancel=lambda: state["cancel"],
            progress=progress,
        )
    assert database.scalar("SELECT COUNT(*) FROM auto_match_candidate") == 0
    assert database.scalar("SELECT COUNT(*) FROM match_group") == 0
