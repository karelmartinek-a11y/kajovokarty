from __future__ import annotations

from kajovokarty.application.audit import AuditService
from kajovokarty.application.pairing import ManualAllocationService
from kajovokarty.application.payment_reconciliation import DocumentPaymentService, DocumentPaymentStatus
from conftest import insert_card, insert_invoice


def test_document_status_is_exactly_three_values_and_manual_payment_is_reversible(database) -> None:
    insert_invoice(database, "i1", "FA1", 10000, date_text="2026-07-30T10:00:00Z")
    database.execute("UPDATE invoice SET paid_at_utc=? WHERE external_id=?", ("2026-07-30T10:00:00Z", "i1"))
    service = DocumentPaymentService(database, ManualAllocationService(database, AuditService()), AuditService())
    assert service.status("i1") == DocumentPaymentStatus.UNPAID
    service.mark_manual_paid("i1")
    assert service.status("i1") == DocumentPaymentStatus.PAID
    service.clear_manual_paid("i1")
    assert service.status("i1") == DocumentPaymentStatus.UNPAID


def test_automatic_match_uses_terminal_only_same_currency_and_two_day_window(database) -> None:
    insert_invoice(database, "i1", "FA1", 10000, currency="EUR", date_text="2026-07-30T10:00:00Z")
    database.execute("UPDATE invoice SET paid_at_utc=? WHERE external_id=?", ("2026-07-30T10:00:00Z", "i1"))
    insert_card(database, "c1", "T1", "0001", 10000, currency="EUR", date_text="2026-08-01T10:00:00Z")
    insert_card(database, "c2", "T1", "0002", 10000, currency="CZK", date_text="2026-07-30T10:00:00Z")
    service = DocumentPaymentService(database, ManualAllocationService(database, AuditService()), AuditService())
    result = service.auto_match()
    assert result.matched == 1
    assert database.scalar("SELECT source_id FROM allocation WHERE invoice_id=? AND active=1", ("i1",)) == "c1"
    assert service.status("i1") == DocumentPaymentStatus.PAID
