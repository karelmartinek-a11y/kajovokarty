from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import uuid4

from ..domain.enums import SourceType
from ..infrastructure.importers.common import utc_now
from ..infrastructure.persistence.database import Database
from .audit import AuditService
from .pairing import DocumentRef, ManualAllocationService, PairingError, SourceRef


class DocumentPaymentStatus(StrEnum):
    UNPAID = "NEUHRAZEN"
    PARTIAL = "ČÁSTEČNÁ ÚHRADA"
    PAID = "UHRAZEN"


@dataclass(frozen=True, slots=True)
class PaymentMatchResult:
    matched: int
    partial: int
    skipped: int
    alerts: int


class DocumentPaymentService:
    """Deterministic document-level payment status and matching rules."""

    def __init__(self, database: Database, pairing: ManualAllocationService, audit: AuditService) -> None:
        self.database = database
        self.pairing = pairing
        self.audit = audit

    def status(self, invoice_id: str) -> DocumentPaymentStatus:
        with self.database.read_connection() as conn:
            row = conn.execute(
                "SELECT i.total_minor,COALESCE(s.manual_paid,0) AS manual_paid,"
                "COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.invoice_id=i.external_id AND a.active=1),0) AS used "
                "FROM invoice i LEFT JOIN invoice_payment_status s ON s.invoice_id=i.external_id WHERE i.external_id=?",
                (invoice_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Doklad neexistuje.")
        if row["manual_paid"]:
            return DocumentPaymentStatus.PAID
        total = int(row["total_minor"])
        used = int(row["used"])
        if used == 0:
            return DocumentPaymentStatus.UNPAID
        if abs(used) >= abs(total):
            return DocumentPaymentStatus.PAID
        return DocumentPaymentStatus.PARTIAL

    def mark_manual_paid(self, invoice_id: str) -> None:
        now = utc_now()
        with self.database.transaction() as conn:
            if conn.execute("SELECT 1 FROM invoice WHERE external_id=?", (invoice_id,)).fetchone() is None:
                raise ValueError("Doklad neexistuje.")
            conn.execute(
                "INSERT INTO invoice_payment_status(invoice_id,manual_paid,manual_paid_at_utc,manual_paid_by,updated_at_utc) VALUES(?,?,?,?,?) "
                "ON CONFLICT(invoice_id) DO UPDATE SET manual_paid=1,manual_paid_at_utc=excluded.manual_paid_at_utc,manual_paid_by=excluded.manual_paid_by,updated_at_utc=excluded.updated_at_utc,row_version=row_version+1",
                (invoice_id, 1, now, "manual", now),
            )

    def clear_manual_paid(self, invoice_id: str) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE invoice_payment_status SET manual_paid=0,manual_paid_at_utc=NULL,manual_paid_by=NULL,updated_at_utc=?,row_version=row_version+1 WHERE invoice_id=?",
                (utc_now(), invoice_id),
            )

    def unlink_allocation(self, allocation_id: str) -> str:
        return self.pairing.remove_allocation(allocation_id)

    def auto_match(self, *, cancel=None, progress=None) -> PaymentMatchResult:
        """Match Booking references first, then terminal amount/date fallback."""
        rows = self.database.query(
            "SELECT i.external_id,i.total_minor,i.currency_code,i.document_date_utc,i.paid_at_utc,"
            "COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.invoice_id=i.external_id AND a.active=1),0) AS used,"
            "GROUP_CONCAT(DISTINCT r.booking_reference) AS booking_refs "
            "FROM invoice i LEFT JOIN reservation_invoice_link l ON l.invoice_id=i.external_id "
            "LEFT JOIN reservation r ON r.uuid=l.reservation_id WHERE i.included=1 AND i.pay_method=2 AND i.paid_at_utc IS NOT NULL GROUP BY i.external_id ORDER BY i.document_date_utc,i.external_id"
        )
        matched = partial = skipped = alerts = 0
        total = max(1, len(rows))
        for index, row in enumerate(rows, start=1):
            if cancel is not None and cancel():
                break
            remaining = int(row["total_minor"]) - int(row["used"])
            if remaining == 0 or self.status(str(row["external_id"])) == DocumentPaymentStatus.PAID:
                skipped += 1
                continue
            booking_refs = [x for x in str(row["booking_refs"] or "").split(",") if x]
            source, booking_seen = self._booking_source(str(row["currency_code"]), booking_refs, remaining)
            if source is None:
                source = self._terminal_source(str(row["currency_code"]), remaining, str(row["paid_at_utc"] or row["document_date_utc"]))
            if source is not None:
                try:
                    self.pairing.pair_one(DocumentRef(str(row["external_id"])), source, amount_minor=remaining)
                    current = self.status(str(row["external_id"]))
                    if current == DocumentPaymentStatus.PAID:
                        matched += 1
                    else:
                        partial += 1
                except PairingError as exc:
                    self._alert(str(row["external_id"]), "MATCH_FAILED", str(exc), source.source_id)
                    alerts += 1
            elif booking_refs and booking_seen:
                self._alert(str(row["external_id"]), "BOOKING_SOURCE_ALREADY_USED", "Booking.com potvrzení se stejným číslem je již plně využité nebo jeho volná částka nestačí.", None, severity="CRITICAL")
                alerts += 1
            if progress:
                progress(index, total, f"Doklady {index}/{len(rows)} – hledám potvrzení úhrady")
        return PaymentMatchResult(matched, partial, skipped, alerts)

    def _booking_source(self, currency: str, refs: list[str], remaining: int) -> tuple[SourceRef | None, bool]:
        if not refs:
            return None, False
        seen = False
        with self.database.read_connection() as conn:
            for ref in refs:
                rows = conn.execute(
                    "SELECT b.row_hash,b.amount_minor,COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='BOOKING' AND a.source_id=b.row_hash AND a.active=1),0) AS used "
                    "FROM booking_payment_line b WHERE b.active_source=1 AND b.currency_code=? AND b.booking_reference=? ORDER BY b.payout_date,b.row_hash",
                    (currency, ref),
                ).fetchall()
                seen = seen or bool(rows)
                for row in rows:
                    if int(row["amount_minor"]) - int(row["used"]) >= abs(remaining):
                        return SourceRef(SourceType.BOOKING, str(row["row_hash"])), True
        return None, seen

    def _terminal_source(self, currency: str, remaining: int, date_text: str) -> SourceRef | None:
        target = date.fromisoformat(date_text[:10])
        with self.database.read_connection() as conn:
            rows = conn.execute(
                "SELECT c.id,c.amount_minor,c.occurred_at,COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='CARD' AND a.source_id=c.id AND a.active=1),0) AS used "
                "FROM card_transaction c WHERE c.currency_code=? ORDER BY c.occurred_at,c.id",
                (currency,),
            ).fetchall()
        for row in rows:
            if abs((date.fromisoformat(str(row["occurred_at"])[:10]) - target).days) <= 2 and int(row["amount_minor"]) - int(row["used"]) >= abs(remaining):
                return SourceRef(SourceType.CARD, str(row["id"]))
        return None

    def _alert(self, invoice_id: str, code: str, message: str, source_id: str | None, *, severity: str = "INFO") -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO payment_matching_alert(id,invoice_id,severity,code,message,source_id,created_at_utc) VALUES(?,?,?,?,?,?,?)",
                (uuid4().hex, invoice_id, severity, code, message, source_id, utc_now()),
            )
