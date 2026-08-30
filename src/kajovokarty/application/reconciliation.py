from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from ..domain.entities import MatchItem
from ..domain.enums import MatchStatus, ObjectSide, SourceType
from ..domain.matching import MatchingCancelled, MatchingSettings, ReconciliationEngine
from ..infrastructure.importers.common import canonical_json, utc_now
from ..infrastructure.persistence.database import Database
from .pairing import DocumentRef, ManualAllocationService, PairingError, SourceRef

CancelCallback = Callable[[], bool]
ProgressCallback = Callable[[int, int, str], None]


class ReconciliationCancelled(RuntimeError):
    pass


class ReconciliationService:
    def __init__(self, database: Database, pairing: ManualAllocationService) -> None:
        self.database = database
        self.pairing = pairing

    def recompute(
        self,
        settings: MatchingSettings,
        *,
        auto_confirm: bool = True,
        cancel: CancelCallback | None = None,
        progress: ProgressCallback | None = None,
    ) -> dict[str, int]:
        if cancel is not None and cancel():
            raise ReconciliationCancelled("Přepočet párování byl bezpečně zrušen před spuštěním.")
        items = self._load_items()
        if progress:
            progress(0, max(1, len(items)), "Generuji deterministické kandidáty")
        try:
            candidates = ReconciliationEngine(settings).generate(items, cancel=cancel)
        except MatchingCancelled as exc:
            raise ReconciliationCancelled(str(exc)) from exc
        if cancel is not None and cancel():
            raise ReconciliationCancelled("Přepočet párování byl bezpečně zrušen.")
        counts = {"candidates": 0, "auto_matched": 0, "auto_failed": 0, "rejected_facts": 0}
        rejected = {row[0] for row in self.database.query("SELECT facts_hash FROM rejected_candidate_fact")}
        total_steps = max(1, len(candidates) * (2 if auto_confirm else 1))
        completed = 0
        with self.database.transaction() as conn:
            for candidate in candidates:
                if cancel is not None and cancel():
                    raise ReconciliationCancelled("Ukládání kandidátů bylo bezpečně zrušeno.")
                if candidate.facts_hash in rejected:
                    counts["rejected_facts"] += 1
                    continue
                now = utc_now()
                conn.execute(
                    "INSERT INTO auto_match_candidate(id,currency_code,document_ids_json,source_refs_json,score,margin,difference_minor,evidence_json,alternatives_json,status,facts_hash,can_auto_match,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(facts_hash,document_ids_json,source_refs_json) DO UPDATE SET score=excluded.score,margin=excluded.margin,difference_minor=excluded.difference_minor,evidence_json=excluded.evidence_json,alternatives_json=excluded.alternatives_json,status=CASE WHEN auto_match_candidate.status='REJECTED' THEN auto_match_candidate.status ELSE excluded.status END,can_auto_match=excluded.can_auto_match,updated_at_utc=excluded.updated_at_utc",
                    (
                        candidate.id,
                        candidate.currency,
                        json.dumps(candidate.document_ids),
                        json.dumps(candidate.source_refs),
                        candidate.score,
                        candidate.margin,
                        candidate.difference_minor,
                        json.dumps([{"code": e.code, "label": e.label, "score_delta": e.score_delta, "detail": e.detail, "conflicting": e.conflicting} for e in candidate.evidence], ensure_ascii=False),
                        json.dumps(candidate.alternatives, ensure_ascii=False),
                        candidate.status.value,
                        candidate.facts_hash,
                        int(candidate.can_auto_match),
                        now,
                        now,
                    ),
                )
                counts["candidates"] += 1
                completed += 1
                if progress:
                    progress(completed, total_steps, f"Ukládám návrhy ({completed}/{len(candidates)})")
        if auto_confirm:
            for candidate in candidates:
                if cancel is not None and cancel():
                    raise ReconciliationCancelled("Automatické potvrzení bylo bezpečně zrušeno.")
                if not candidate.can_auto_match or candidate.facts_hash in rejected:
                    continue
                try:
                    sources = [_parse_source_ref(value) for value in candidate.source_refs]
                    group_id, _ = self.pairing.pair(
                        [DocumentRef(value) for value in candidate.document_ids],
                        sources,
                        correlation_id=None,
                        human_label="Automatické párování",
                    )
                    with self.database.transaction() as conn:
                        conn.execute("UPDATE allocation SET method='AUTO',row_version=row_version+1 WHERE group_id=?", (group_id,))
                        conn.execute("UPDATE match_group SET status='UNMATCHED',manual_lock=0,updated_at_utc=?,row_version=row_version+1 WHERE id=?", (utc_now(), group_id))
                        ManualAllocationService._recalculate_group(conn, group_id)
                        conn.execute("UPDATE auto_match_candidate SET status='ACCEPTED',updated_at_utc=? WHERE id=?", (utc_now(), candidate.id))
                    counts["auto_matched"] += 1
                except Exception as exc:
                    counts["auto_failed"] += 1
                    message = _safe_failure(exc)
                    with self.database.transaction() as conn:
                        row = conn.execute("SELECT alternatives_json FROM auto_match_candidate WHERE id=?", (candidate.id,)).fetchone()
                        alternatives = json.loads(row["alternatives_json"] or "[]") if row else []
                        alternatives.append(f"Automatické potvrzení selhalo: {message}")
                        conn.execute("UPDATE auto_match_candidate SET status='CONFLICT',can_auto_match=0,alternatives_json=?,updated_at_utc=? WHERE id=?", (canonical_json(alternatives), utc_now(), candidate.id))
                finally:
                    completed += 1
                    if progress:
                        progress(completed, total_steps, f"Ověřuji automatické vazby ({completed-len(candidates)}/{len(candidates)})")
        if progress:
            progress(total_steps, total_steps, "Přepočet párování dokončen")
        return counts

    def accept_candidate(self, candidate_id: str) -> tuple[str, str]:
        rows = self.database.query("SELECT * FROM auto_match_candidate WHERE id=?", (candidate_id,))
        if not rows:
            raise ValueError("Návrh neexistuje.")
        candidate = rows[0]
        if candidate["status"] == "REJECTED":
            raise ValueError("Odmítnutý návrh nelze potvrdit bez změny vstupních faktů.")
        documents = [DocumentRef(value) for value in json.loads(candidate["document_ids_json"])]
        sources = [_parse_source_ref(value) for value in json.loads(candidate["source_refs_json"])]
        group_id, command_id = self.pairing.pair(documents, sources, human_label="Potvrzení návrhu")
        self.database.execute("UPDATE auto_match_candidate SET status='ACCEPTED',updated_at_utc=? WHERE id=?", (utc_now(), candidate_id))
        return group_id, command_id

    def reject_candidate(self, candidate_id: str, command_id: str) -> None:
        with self.database.transaction() as conn:
            row = conn.execute("SELECT facts_hash FROM auto_match_candidate WHERE id=?", (candidate_id,)).fetchone()
            if row is None:
                raise ValueError("Návrh neexistuje.")
            conn.execute("UPDATE auto_match_candidate SET status='REJECTED',can_auto_match=0,updated_at_utc=? WHERE id=?", (utc_now(), candidate_id))
            conn.execute("INSERT OR REPLACE INTO rejected_candidate_fact(facts_hash,candidate_id,rejected_at_utc,command_id) VALUES(?,?,?,?)", (row["facts_hash"], candidate_id, utc_now(), command_id))

    def _load_items(self) -> list[MatchItem]:
        items: list[MatchItem] = []
        with self.database.read_connection() as conn:
            for row in conn.execute(
                "SELECT i.*, "
                "(SELECT r.internal_code FROM reservation_invoice_link l JOIN reservation r ON r.uuid=l.reservation_id WHERE l.invoice_id=i.external_id ORDER BY r.uuid LIMIT 1) AS internal_code, "
                "(SELECT r.booking_reference FROM reservation_invoice_link l JOIN reservation r ON r.uuid=l.reservation_id WHERE l.invoice_id=i.external_id AND r.booking_reference IS NOT NULL ORDER BY r.uuid LIMIT 1) AS booking_reference, "
                "EXISTS(SELECT 1 FROM reservation_invoice_link l WHERE l.invoice_id=i.external_id) AS direct_link, "
                "EXISTS(SELECT 1 FROM match_group_document d JOIN match_group g ON g.id=d.group_id WHERE d.invoice_id=i.external_id AND d.active=1 AND g.manual_lock=1 AND g.status<>'REVERSED') AS manual_locked "
                "FROM invoice i WHERE i.included=1"
            ):
                used = conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM allocation WHERE invoice_id=? AND active=1", (row["external_id"],)).fetchone()[0]
                items.append(MatchItem("INVOICE", row["external_id"], ObjectSide.DOCUMENT, row["total_minor"], row["total_minor"] - used, row["currency_code"], _date(row["document_date_utc"]), row["row_version"], row["booking_reference"], row["internal_code"], _datetime(row["paid_at_utc"]), bool(row["manual_locked"]), MatchStatus(row["status"]), {"reservation_invoice_link": bool(row["direct_link"])}))
            for row in conn.execute(
                "SELECT b.*,EXISTS(SELECT 1 FROM match_group_source s JOIN match_group g ON g.id=s.group_id WHERE s.entity_type='BOOKING' AND s.entity_id=b.row_hash AND s.active=1 AND g.manual_lock=1 AND g.status<>'REVERSED') AS manual_locked FROM booking_payment_line b WHERE b.active_source=1"
            ):
                used = conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM allocation WHERE source_type='BOOKING' AND source_id=? AND active=1", (row["row_hash"],)).fetchone()[0]
                effective = row["payout_date"] or row["arrival"] or str(row["first_seen_utc"])[:10]
                items.append(MatchItem("BOOKING", f"BOOKING:{row['row_hash']}", ObjectSide.SOURCE, row["amount_minor"], row["amount_minor"] - used, row["currency_code"], _date(effective), row["row_version"], row["booking_reference"], None, None, bool(row["manual_locked"]), MatchStatus(row["status"]), {}))
            for row in conn.execute(
                "SELECT c.*,EXISTS(SELECT 1 FROM match_group_source s JOIN match_group g ON g.id=s.group_id WHERE s.entity_type='CARD' AND s.entity_id=c.id AND s.active=1 AND g.manual_lock=1 AND g.status<>'REVERSED') AS manual_locked FROM card_transaction c"
            ):
                used = conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM allocation WHERE source_type='CARD' AND source_id=? AND active=1", (row["id"],)).fetchone()[0]
                items.append(MatchItem("CARD", f"CARD:{row['id']}", ObjectSide.SOURCE, row["amount_minor"], row["amount_minor"] - used, row["currency_code"], _date(row["occurred_at"]), row["row_version"], None, None, None, bool(row["manual_locked"]), MatchStatus(row["status"]), {}))
        return items


def _parse_source_ref(value: str) -> SourceRef:
    prefix, separator, identifier = value.partition(":")
    if not separator:
        raise ValueError(f"Neplatná reference zdroje: {value}")
    return SourceRef(SourceType(prefix), identifier)


def _date(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _safe_failure(exc: Exception) -> str:
    if isinstance(exc, PairingError):
        return str(exc)
    return f"{type(exc).__name__}: {str(exc)[:200]}"
