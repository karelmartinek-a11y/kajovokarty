from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from ..domain.money import Money
from ..infrastructure.persistence.database import Database


@dataclass(frozen=True, slots=True)
class SearchResult:
    object_ref: str
    object_type: str
    primary_label: str
    secondary_text: str
    technical_ids: str
    amount_text: str
    date_text: str


class SearchService:
    """Index and relationship projection for every live SSOT object.

    The search index is deliberately rebuilt from authoritative relational tables.  It
    is a projection only; deleting/rebuilding it can never alter domain data.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def rebuild_index(self) -> int:
        rows: list[tuple[str, str, str, str, str, str, str]] = []
        with self.database.read_connection() as conn:
            for row in conn.execute(
                "SELECT external_id,code,total_minor,currency_code,document_date_utc,paid_at_utc,status "
                "FROM invoice"
            ):
                rows.append(
                    (
                        f"INVOICE:{row['external_id']}",
                        "Doklad",
                        row["code"],
                        f"{row['status']} • {row['currency_code']}",
                        row["external_id"],
                        self._amount_text(row["total_minor"], row["currency_code"]),
                        row["document_date_utc"],
                    )
                )
            for row in conn.execute(
                "SELECT uuid,internal_code,booking_reference,source_name,arrival,departure FROM reservation"
            ):
                rows.append(
                    (
                        f"RESERVATION:{row['uuid']}",
                        "Rezervace",
                        row["internal_code"],
                        f"{row['source_name'] or ''} • Booking {row['booking_reference'] or '—'}",
                        f"{row['uuid']} {row['booking_reference'] or ''}",
                        "",
                        f"{row['arrival'] or ''} {row['departure'] or ''}",
                    )
                )
            for row in conn.execute(
                "SELECT l.row_hash,l.booking_reference,b.payment_id,l.amount_minor,l.currency_code,l.payout_date,l.status,l.guest_name "
                "FROM booking_payment_line l JOIN booking_payout_batch b ON b.id=l.batch_id WHERE l.active_source=1"
            ):
                rows.append(
                    (
                        f"BOOKING:{row['row_hash']}",
                        "Booking.com",
                        row["booking_reference"],
                        f"Výplata {row['payment_id']} • {row['status']} • {row['guest_name'] or ''}",
                        f"{row['row_hash']} {row['payment_id']}",
                        self._amount_text(row["amount_minor"], row["currency_code"]),
                        row["payout_date"] or "",
                    )
                )
            for row in conn.execute(
                "SELECT id,terminal_id,seq_id,arn,authorization_code,masked_card,amount_minor,currency_code,"
                "occurred_at,status FROM card_transaction"
            ):
                rows.append(
                    (
                        f"CARD:{row['id']}",
                        "Karta",
                        row["seq_id"],
                        f"Terminál {row['terminal_id']} • {row['status']} • {row['masked_card'] or ''}",
                        f"{row['id']} {row['seq_id']} {row['arn'] or ''} {row['authorization_code'] or ''}",
                        self._amount_text(row["amount_minor"], row["currency_code"]),
                        row["occurred_at"],
                    )
                )
            for row in conn.execute(
                "SELECT id,receipt_number,variable_symbol,amount_minor,currency_code,occurred_at,status,client "
                "FROM cashbook_card_transaction"
            ):
                rows.append(
                    (
                        f"CASHBOOK_CARD:{row['id']}", "Pokladní karta", row["receipt_number"],
                        f"{row['status']} • {row['client'] or ''}",
                        f"{row['id']} {row['receipt_number']} {row['variable_symbol'] or ''}",
                        self._amount_text(row["amount_minor"], row["currency_code"]), row["occurred_at"],
                    )
                )
            for row in conn.execute(
                "SELECT id,status,currency_code,difference_minor,updated_at_utc,allocation_mode FROM match_group"
            ):
                rows.append(
                    (
                        f"MATCH_GROUP:{row['id']}",
                        "Vyrovnávací skupina",
                        f"Skupina {row['id'][:8]}",
                        f"{row['status']} • {row['allocation_mode']}",
                        row["id"],
                        self._amount_text(row["difference_minor"], row["currency_code"]),
                        row["updated_at_utc"],
                    )
                )
            for row in conn.execute(
                "SELECT id,type,name,amount_minor,currency_code,note,created_at_utc FROM manual_settlement "
                "WHERE active=1"
            ):
                label = row["name"] or ("Hotovost" if row["type"] == "CASH" else "Jiný ruční zdroj")
                rows.append(
                    (
                        f"MANUAL:{row['id']}",
                        "Ruční zdroj",
                        label,
                        f"{row['type']} • {row['note'] or ''}",
                        row["id"],
                        self._amount_text(row["amount_minor"], row["currency_code"]),
                        row["created_at_utc"],
                    )
                )

            for row in conn.execute(
                "SELECT id,group_id,source_type,source_id,invoice_id,amount_minor,method,active,created_at_utc "
                "FROM allocation"
            ):
                group = conn.execute("SELECT currency_code FROM match_group WHERE id=?", (row["group_id"],)).fetchone()
                currency = str(group["currency_code"]) if group else "CZK"
                rows.append(
                    (
                        f"ALLOCATION:{row['id']}",
                        "Konkrétní vazba",
                        f"Vazba {row['id'][:8]}",
                        f"{row['source_type']}:{row['source_id']} → doklad {row['invoice_id']} • {row['method']} • "
                        f"{'aktivní' if row['active'] else 'rozpojená'}",
                        f"{row['id']} {row['group_id']} {row['source_type']}:{row['source_id']} {row['invoice_id']}",
                        self._amount_text(row["amount_minor"], currency),
                        row["created_at_utc"],
                    )
                )
            for source, table in (
                ("Better Hotel", "api_sync_run"),
                ("Booking.com", "booking_import_run"),
                ("Banka", "bank_import_run"),
            ):
                for row in conn.execute(
                    f"SELECT id,correlation_id,state,counts_json,error_json,started_at_utc,finished_at_utc FROM {table}"
                ):
                    rows.append(
                        (
                            f"IMPORT_RUN:{row['id']}",
                            "Importní běh",
                            f"{source} {row['id'][:8]}",
                            f"{row['state']} • {row['counts_json']} • {row['error_json'] or ''}",
                            f"{row['id']} {row['correlation_id']} {source}",
                            "",
                            row["finished_at_utc"] or row["started_at_utc"],
                        )
                    )
            for row in conn.execute(
                "SELECT id,run_type,run_id,row_no,reason_code,reason_text,state,created_at_utc FROM quarantined_source_row"
            ):
                rows.append(
                    (
                        f"QUARANTINE:{row['id']}",
                        "Karanténní řádek",
                        f"Karanténa řádek {row['row_no']}",
                        f"{row['run_type']} • {row['reason_code']} • {row['state']} • {row['reason_text']}",
                        f"{row['id']} {row['run_id']} {row['reason_code']}",
                        "",
                        row["created_at_utc"],
                    )
                )
            for row in conn.execute(
                "SELECT event_id,command_id,correlation_id,event_code,operation_label,object_ref,created_at_utc "
                "FROM audit_event"
            ):
                rows.append(
                    (
                        f"AUDIT:{row['event_id']}",
                        "Auditní událost",
                        row["operation_label"],
                        f"{row['event_code']} • {row['object_ref'] or 'bez objektu'}",
                        f"{row['event_id']} {row['command_id'] or ''} {row['correlation_id']} {row['object_ref'] or ''}",
                        "",
                        row["created_at_utc"],
                    )
                )

            # Appendix B objects that must not become invisible technical dead ends.
            for row in conn.execute(
                "SELECT id,score,margin,difference_minor,currency_code,status,document_ids_json,source_refs_json,"
                "facts_hash,created_at_utc FROM auto_match_candidate"
            ):
                rows.append(
                    (
                        f"CANDIDATE:{row['id']}",
                        "Návrh párování",
                        f"Návrh {row['id'][:8]}",
                        f"Score {row['score']} • margin {row['margin']} • {row['status']}",
                        f"{row['id']} {row['facts_hash']} {row['document_ids_json']} {row['source_refs_json']}",
                        self._amount_text(row["difference_minor"], row["currency_code"]),
                        row["created_at_utc"],
                    )
                )
            for row in conn.execute(
                "SELECT id,reservation_id,candidate,label,status,parser_version,extracted_at_utc "
                "FROM booking_reference_extraction"
            ):
                rows.append(
                    (
                        f"BOOKING_REFERENCE:{row['id']}",
                        "Booking reference",
                        row["candidate"],
                        f"{row['status']} • {row['label']} • rezervace {row['reservation_id']}",
                        f"{row['id']} {row['reservation_id']} {row['candidate']} {row['parser_version']}",
                        "",
                        row["extracted_at_utc"],
                    )
                )
            for row in conn.execute(
                "SELECT external_id,reservation_id,total_minor,balance_minor,currency_code,is_closed,is_locked "
                "FROM bill"
            ):
                rows.append(
                    (
                        f"BILL:{row['external_id']}",
                        "Účet",
                        f"Účet {row['external_id']}",
                        f"Rezervace {row['reservation_id'] or '—'} • uzavřen {bool(row['is_closed'])} • "
                        f"uzamčen {bool(row['is_locked'])}",
                        f"{row['external_id']} {row['reservation_id'] or ''}",
                        self._amount_text(row["balance_minor"] or row["total_minor"] or 0, row["currency_code"] or "CZK"),
                        "",
                    )
                )
            for row in conn.execute(
                "SELECT external_id,bill_id,amount_minor,currency_code FROM bill_item"
            ):
                rows.append(
                    (
                        f"BILL_ITEM:{row['external_id']}",
                        "Položka účtu",
                        f"Položka {row['external_id']}",
                        f"Účet {row['bill_id']}",
                        f"{row['external_id']} {row['bill_id']}",
                        self._amount_text(row["amount_minor"], row["currency_code"]),
                        "",
                    )
                )
            for row in conn.execute(
                "SELECT id,object_ref,changed_fields_json,affected_group_ids_json,state,detected_at_utc "
                "FROM source_revision_alert"
            ):
                changed = self._safe_json_list(row["changed_fields_json"])
                groups = self._safe_json_list(row["affected_group_ids_json"])
                rows.append(
                    (
                        f"REVISION_ALERT:{row['id']}",
                        "Upozornění na změnu zdroje",
                        f"Změna {row['object_ref']}",
                        f"{row['state']} • pole: {', '.join(changed) or '—'} • skupiny: {len(groups)}",
                        f"{row['id']} {row['object_ref']} {' '.join(groups)}",
                        "",
                        row["detected_at_utc"],
                    )
                )
        with self.database.transaction() as conn:
            conn.execute("DELETE FROM global_search")
            conn.executemany(
                "INSERT INTO global_search(object_ref,object_type,primary_label,secondary_text,technical_ids,"
                "amount_text,date_text) VALUES(?,?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    @staticmethod
    def _safe_json_list(value: Any) -> list[str]:
        try:
            parsed = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @staticmethod
    def _amount_text(amount_minor: int, currency_code: str) -> str:
        """Keep a machine-searchable prefix and a human readable representation."""
        return f"{int(amount_minor)} {currency_code} • {Money(int(amount_minor), currency_code).format()}"

    def search(self, query: str, *, limit: int = 100) -> list[SearchResult]:
        text = query.strip()
        if not text:
            return []
        fts = " AND ".join(f'"{token}"*' for token in re.findall(r"[\w.-]+", text, re.UNICODE))
        if not fts:
            return []
        try:
            rows = self.database.query(
                "SELECT object_ref,object_type,primary_label,secondary_text,technical_ids,amount_text,date_text "
                "FROM global_search WHERE global_search MATCH ? ORDER BY rank LIMIT ?",
                (fts, limit),
            )
        except Exception:
            self.rebuild_index()
            rows = self.database.query(
                "SELECT object_ref,object_type,primary_label,secondary_text,technical_ids,amount_text,date_text "
                "FROM global_search WHERE global_search MATCH ? ORDER BY rank LIMIT ?",
                (fts, limit),
            )
        return [SearchResult(**dict(row)) for row in rows]

    def related(self, object_ref: str) -> list[SearchResult]:
        kind, _, identifier = object_ref.partition(":")
        refs: list[str] = []
        with self.database.read_connection() as conn:
            if kind == "INVOICE":
                refs.extend(
                    f"RESERVATION:{row[0]}"
                    for row in conn.execute(
                        "SELECT reservation_id FROM reservation_invoice_link WHERE invoice_id=?", (identifier,)
                    )
                )
                refs.extend(
                    f"MATCH_GROUP:{row[0]}"
                    for row in conn.execute(
                        "SELECT group_id FROM match_group_document WHERE invoice_id=? AND active=1", (identifier,)
                    )
                )
                refs.extend(
                    f"BILL_ITEM:{row[0]}"
                    for row in conn.execute(
                        "SELECT external_id FROM bill_item WHERE external_id IN "
                        "(SELECT bill_item_id FROM invoice_item WHERE invoice_id=? AND bill_item_id IS NOT NULL)",
                        (identifier,),
                    )
                )
            elif kind == "RESERVATION":
                refs.extend(
                    f"INVOICE:{row[0]}"
                    for row in conn.execute(
                        "SELECT invoice_id FROM reservation_invoice_link WHERE reservation_id=?", (identifier,)
                    )
                )
                refs.extend(
                    f"BILL:{row[0]}" for row in conn.execute("SELECT external_id FROM bill WHERE reservation_id=?", (identifier,))
                )
                refs.extend(
                    f"BOOKING_REFERENCE:{row[0]}"
                    for row in conn.execute(
                        "SELECT id FROM booking_reference_extraction WHERE reservation_id=?", (identifier,)
                    )
                )
            elif kind in {"BOOKING", "CARD", "CASH", "OTHER"}:
                refs.extend(
                    f"MATCH_GROUP:{row[0]}"
                    for row in conn.execute(
                        "SELECT group_id FROM match_group_source WHERE entity_type=? AND entity_id=? AND active=1",
                        (kind, identifier),
                    )
                )
            elif kind == "MANUAL":
                refs.extend(
                    f"MATCH_GROUP:{row[0]}"
                    for row in conn.execute(
                        "SELECT group_id FROM manual_settlement WHERE id=?", (identifier,)
                    )
                )
            elif kind == "MATCH_GROUP":
                refs.extend(
                    f"INVOICE:{row[0]}"
                    for row in conn.execute(
                        "SELECT invoice_id FROM match_group_document WHERE group_id=? AND active=1", (identifier,)
                    )
                )
                refs.extend(
                    f"{row[0]}:{row[1]}"
                    for row in conn.execute(
                        "SELECT entity_type,entity_id FROM match_group_source WHERE group_id=? AND active=1",
                        (identifier,),
                    )
                )
                refs.extend(
                    f"REVISION_ALERT:{row[0]}"
                    for row in conn.execute(
                        "SELECT id FROM source_revision_alert WHERE affected_group_ids_json LIKE ?",
                        (f'%"{identifier}"%',),
                    )
                )
            elif kind == "ALLOCATION":
                row = conn.execute(
                    "SELECT group_id,invoice_id,source_type,source_id FROM allocation WHERE id=?", (identifier,)
                ).fetchone()
                if row is not None:
                    refs.extend(
                        [f"MATCH_GROUP:{row['group_id']}", f"INVOICE:{row['invoice_id']}", f"{row['source_type']}:{row['source_id']}"]
                    )
            elif kind == "BILL":
                refs.extend(
                    f"RESERVATION:{row[0]}"
                    for row in conn.execute("SELECT reservation_id FROM bill WHERE external_id=?", (identifier,))
                    if row[0]
                )
                refs.extend(
                    f"BILL_ITEM:{row[0]}" for row in conn.execute("SELECT external_id FROM bill_item WHERE bill_id=?", (identifier,))
                )
            elif kind == "BILL_ITEM":
                refs.extend(
                    f"BILL:{row[0]}" for row in conn.execute("SELECT bill_id FROM bill_item WHERE external_id=?", (identifier,))
                )
                refs.extend(
                    f"INVOICE:{row[0]}" for row in conn.execute("SELECT invoice_id FROM invoice_item WHERE bill_item_id=?", (identifier,))
                )
            elif kind == "BOOKING_REFERENCE":
                refs.extend(
                    f"RESERVATION:{row[0]}"
                    for row in conn.execute(
                        "SELECT reservation_id FROM booking_reference_extraction WHERE id=?", (identifier,)
                    )
                )
            elif kind == "REVISION_ALERT":
                row = conn.execute(
                    "SELECT object_ref,affected_group_ids_json FROM source_revision_alert WHERE id=?", (identifier,)
                ).fetchone()
                if row is not None:
                    refs.append(str(row["object_ref"]))
                    refs.extend(f"MATCH_GROUP:{group_id}" for group_id in self._safe_json_list(row["affected_group_ids_json"]))
            elif kind == "CANDIDATE":
                row = conn.execute(
                    "SELECT document_ids_json,source_refs_json FROM auto_match_candidate WHERE id=?", (identifier,)
                ).fetchone()
                if row is not None:
                    refs.extend(f"INVOICE:{value}" for value in self._safe_json_list(row["document_ids_json"]))
                    refs.extend(self._safe_json_list(row["source_refs_json"]))
            elif kind == "IMPORT_RUN":
                refs.extend(
                    f"QUARANTINE:{row[0]}"
                    for row in conn.execute(
                        "SELECT id FROM quarantined_source_row WHERE run_id=? ORDER BY row_no", (identifier,)
                    )
                )
                refs.extend(
                    f"AUDIT:{row[0]}"
                    for row in conn.execute(
                        "SELECT event_id FROM audit_event WHERE correlation_id IN ("
                        "SELECT correlation_id FROM api_sync_run WHERE id=? "
                        "UNION SELECT correlation_id FROM booking_import_run WHERE id=? "
                        "UNION SELECT correlation_id FROM bank_import_run WHERE id=?"
                        ") ORDER BY created_at_utc",
                        (identifier, identifier, identifier),
                    )
                )
            elif kind == "QUARANTINE":
                row = conn.execute(
                    "SELECT run_id FROM quarantined_source_row WHERE id=?", (identifier,)
                ).fetchone()
                if row is not None:
                    refs.append(f"IMPORT_RUN:{row['run_id']}")
            elif kind == "AUDIT":
                row = conn.execute(
                    "SELECT object_ref FROM audit_event WHERE event_id=?", (identifier,)
                ).fetchone()
                if row is not None and row["object_ref"]:
                    refs.append(str(row["object_ref"]))
        return self._results_for_refs(refs)

    def _results_for_refs(self, refs: Iterable[str]) -> list[SearchResult]:
        unique_refs = list(dict.fromkeys(ref for ref in refs if ref))
        if not unique_refs:
            return []
        placeholders = ",".join("?" for _ in unique_refs)
        rows = self.database.query(
            "SELECT object_ref,object_type,primary_label,secondary_text,technical_ids,amount_text,date_text "
            f"FROM global_search WHERE object_ref IN ({placeholders})",
            unique_refs,
        )
        by_ref = {str(row["object_ref"]): SearchResult(**dict(row)) for row in rows}
        return [by_ref[ref] for ref in unique_refs if ref in by_ref]
