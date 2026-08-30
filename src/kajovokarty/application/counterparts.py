from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from dateutil.parser import isoparse

from ..infrastructure.persistence.database import Database


class CounterpartSearchError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CounterpartCandidate:
    object_type: str
    object_id: str
    label: str
    currency: str
    remaining_minor: int
    row_version: int
    status: str
    date_text: str
    date_distance_days: int | None
    score: int
    amount_difference_minor: int
    evidence: tuple[str, ...]


class CounterpartSearchService:
    """Deterministic, read-only manual counterpart search.

    Results outside the automatic seven-day window are intentionally only
    explanatory candidates; this service never commits a match.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def search(
        self,
        object_type: str,
        object_id: str,
        *,
        window_days: int | None = 7,
        limit: int = 500,
    ) -> list[CounterpartCandidate]:
        kind = object_type.upper()
        if kind == "INVOICE":
            anchor = self._invoice(object_id)
            candidates = self._sources(anchor, window_days)
        elif kind in {"BOOKING", "CARD", "MANUAL"}:
            anchor = self._source(kind, object_id)
            candidates = self._invoices(anchor, window_days)
        else:
            raise CounterpartSearchError("Možné protějšky lze hledat pouze pro doklad nebo zdroj úhrady.")
        return sorted(
            candidates,
            key=lambda item: (
                -item.score,
                abs(item.amount_difference_minor),
                item.date_distance_days if item.date_distance_days is not None else 10**9,
                item.object_type,
                item.object_id,
            ),
        )[:limit]

    def _invoice(self, invoice_id: str) -> dict[str, Any]:
        rows = self.database.query(
            "SELECT i.*,i.total_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a "
            "WHERE a.invoice_id=i.external_id AND a.active=1),0) AS remaining_minor "
            "FROM invoice i WHERE i.external_id=?",
            (invoice_id,),
        )
        if not rows:
            raise CounterpartSearchError("Doklad nebyl nalezen.")
        row = dict(rows[0])
        row["kind"] = "INVOICE"
        row["date_value"] = row.get("paid_at_utc") or row.get("document_date_utc")
        row["booking_references"] = {
            str(value[0])
            for value in self.database.query(
                "SELECT DISTINCT r.booking_reference FROM reservation_invoice_link ril "
                "JOIN reservation r ON r.uuid=ril.reservation_id "
                "WHERE ril.invoice_id=? AND r.booking_reference IS NOT NULL",
                (invoice_id,),
            )
        }
        return row

    def _source(self, kind: str, object_id: str) -> dict[str, Any]:
        if kind == "BOOKING":
            rows = self.database.query(
                "SELECT b.*,b.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a "
                "WHERE a.source_type='BOOKING' AND a.source_id=b.row_hash AND a.active=1),0) AS remaining_minor "
                "FROM booking_payment_line b WHERE b.row_hash=? AND b.active_source=1",
                (object_id,),
            )
            date_key = "payout_date"
        elif kind == "CARD":
            rows = self.database.query(
                "SELECT c.*,c.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a "
                "WHERE a.source_type='CARD' AND a.source_id=c.id AND a.active=1),0) AS remaining_minor "
                "FROM card_transaction c WHERE c.id=?",
                (object_id,),
            )
            date_key = "occurred_at"
        else:
            rows = self.database.query(
                "SELECT m.*,m.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a "
                "WHERE a.source_type=m.type AND a.source_id=m.id AND a.active=1),0) AS remaining_minor "
                "FROM manual_settlement m WHERE m.id=? AND m.active=1",
                (object_id,),
            )
            date_key = "created_at_utc"
        if not rows:
            raise CounterpartSearchError("Zdroj úhrady nebyl nalezen nebo už není aktivní.")
        row = dict(rows[0])
        row["kind"] = kind
        row["date_value"] = row.get(date_key)
        return row

    def _sources(self, anchor: dict[str, Any], window_days: int | None) -> list[CounterpartCandidate]:
        currency = str(anchor["currency_code"])
        amount = int(anchor["remaining_minor"])
        if amount == 0:
            return []
        rows: list[dict[str, Any]] = []
        for row in self.database.query(
            "SELECT 'BOOKING' AS kind,b.row_hash AS object_id,b.booking_reference AS label,b.currency_code,b.amount_minor,"
            "b.payout_date AS date_value,b.status,b.row_version,"
            "b.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='BOOKING' "
            "AND a.source_id=b.row_hash AND a.active=1),0) AS remaining_minor "
            "FROM booking_payment_line b WHERE b.active_source=1 AND b.currency_code=?",
            (currency,),
        ):
            rows.append(dict(row))
        for row in self.database.query(
            "SELECT 'CARD' AS kind,c.id AS object_id,c.seq_id AS label,c.currency_code,c.amount_minor,"
            "c.occurred_at AS date_value,c.status,c.row_version,"
            "c.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type='CARD' "
            "AND a.source_id=c.id AND a.active=1),0) AS remaining_minor "
            "FROM card_transaction c WHERE c.currency_code=?",
            (currency,),
        ):
            rows.append(dict(row))
        for row in self.database.query(
            "SELECT 'MANUAL' AS kind,m.id AS object_id,COALESCE(m.name,m.type) AS label,m.currency_code,m.amount_minor,"
            "m.created_at_utc AS date_value,'MANUAL' AS status,m.row_version,"
            "m.amount_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.source_type=m.type "
            "AND a.source_id=m.id AND a.active=1),0) AS remaining_minor "
            "FROM manual_settlement m WHERE m.active=1 AND m.currency_code=?",
            (currency,),
        ):
            rows.append(dict(row))
        return [candidate for row in rows if (candidate := self._candidate(anchor, row, window_days)) is not None]

    def _invoices(self, anchor: dict[str, Any], window_days: int | None) -> list[CounterpartCandidate]:
        rows = self.database.query(
            "SELECT 'INVOICE' AS kind,i.external_id AS object_id,i.code AS label,i.currency_code,i.total_minor AS amount_minor,"
            "COALESCE(i.paid_at_utc,i.document_date_utc) AS date_value,i.status,i.row_version,"
            "i.total_minor-COALESCE((SELECT SUM(a.amount_minor) FROM allocation a WHERE a.invoice_id=i.external_id "
            "AND a.active=1),0) AS remaining_minor FROM invoice i WHERE i.included=1 AND i.currency_code=?",
            (anchor["currency_code"],),
        )
        candidates: list[CounterpartCandidate] = []
        for source_row in rows:
            row = dict(source_row)
            row["booking_references"] = {
                str(value[0])
                for value in self.database.query(
                    "SELECT DISTINCT r.booking_reference FROM reservation_invoice_link ril "
                    "JOIN reservation r ON r.uuid=ril.reservation_id "
                    "WHERE ril.invoice_id=? AND r.booking_reference IS NOT NULL",
                    (row["object_id"],),
                )
            }
            candidate = self._candidate(row, anchor, window_days, result_row=row)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _candidate(
        self,
        document: dict[str, Any],
        source: dict[str, Any],
        window_days: int | None,
        *,
        result_row: dict[str, Any] | None = None,
    ) -> CounterpartCandidate | None:
        doc_remaining = int(document["remaining_minor"])
        source_remaining = int(source["remaining_minor"])
        if doc_remaining == 0 or source_remaining == 0:
            return None
        if (doc_remaining > 0) != (source_remaining > 0):
            return None
        distance = self._distance(document.get("date_value"), source.get("date_value"))
        if window_days is not None and distance is not None and distance > window_days:
            return None
        difference = doc_remaining - source_remaining
        evidence: list[str] = ["Stejná měna", "Účetně kompatibilní znaménko"]
        score = 0
        source_kind = str(source["kind"])
        exact_amount = difference == 0
        if source_kind == "BOOKING":
            reference = str(source.get("booking_reference") or source.get("label") or "")
            booking_refs = set(document.get("booking_references") or ())
            if reference and reference in booking_refs:
                score += 45
                evidence.append("Přesné Booking.com číslo (+45)")
                score += 30
                evidence.append("Přímá vazba rezervace–doklad (+30)")
            if exact_amount:
                score += 15
                evidence.append("Přesný finanční součet (+15)")
            score += self._booking_date_score(distance, evidence)
        elif source_kind == "CARD":
            if exact_amount:
                score += 60
                evidence.append("Přesný finanční součet (+60)")
            score += self._card_date_score(distance, evidence)
            if document.get("paid_at_utc"):
                score += 5
                evidence.append("Doklad má paid_at (+5)")
        else:
            if exact_amount:
                score += 60
                evidence.append("Přesná částka ručního zdroje (+60)")
            score += self._card_date_score(distance, evidence)
        if window_days is not None and window_days > 7 and (distance or 0) > 7:
            evidence.append("Mimo automatické sedmidenní okno – pouze návrh")
        target = result_row or source
        return CounterpartCandidate(
            object_type=str(target["kind"]),
            object_id=str(target["object_id"]),
            label=str(target.get("label") or target["object_id"]),
            currency=str(target["currency_code"]),
            remaining_minor=int(target["remaining_minor"]),
            row_version=int(target.get("row_version") or 1),
            status=str(target.get("status") or "UNMATCHED"),
            date_text=str(target.get("date_value") or ""),
            date_distance_days=distance,
            score=max(0, min(100, score)),
            amount_difference_minor=difference,
            evidence=tuple(evidence),
        )

    @staticmethod
    def _distance(left: Any, right: Any) -> int | None:
        left_date = CounterpartSearchService._date(left)
        right_date = CounterpartSearchService._date(right)
        if left_date is None or right_date is None:
            return None
        return abs((left_date - right_date).days)

    @staticmethod
    def _date(value: Any) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.astimezone(UTC).date() if value.tzinfo else value.date()
        if isinstance(value, date):
            return value
        text = str(value)
        try:
            return isoparse(text).date()
        except (TypeError, ValueError, OverflowError):
            try:
                return date.fromisoformat(text[:10])
            except (TypeError, ValueError):
                return None

    @staticmethod
    def _booking_date_score(distance: int | None, evidence: list[str]) -> int:
        value = 5 if distance is not None and distance <= 2 else 3 if distance is not None and distance <= 4 else 1 if distance is not None and distance <= 7 else 0
        if value:
            evidence.append(f"Datumová vzdálenost {distance} dní (+{value})")
        return value

    @staticmethod
    def _card_date_score(distance: int | None, evidence: list[str]) -> int:
        value = 25 if distance is not None and distance <= 2 else 18 if distance is not None and distance <= 4 else 10 if distance is not None and distance <= 7 else 0
        if value:
            evidence.append(f"Datumová vzdálenost {distance} dní (+{value})")
        return value
