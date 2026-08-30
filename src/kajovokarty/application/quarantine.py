from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ..infrastructure.importers.bank_file import BankFileImportService, BankImportReport
from ..infrastructure.importers.booking_csv import BookingCsvImportService, BookingImportReport
from ..infrastructure.importers.common import ImportValidationError, canonical_json, normalize_text, utc_now
from ..infrastructure.persistence.database import Database
from .audit import AuditContext, AuditService


class QuarantineError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MappingDecision:
    source_kind: str
    field_name: str
    raw_value: str
    mapped_meaning: str


class QuarantineService:
    """Audited quarantine decisions and deterministic one-row reprocessing."""

    _FIELDS = {
        "BOOKING": {"reservation_status": "Status rezervace", "payment_status": "Status platby"},
        "BANK": {"transaction_type": "Typ transakce"},
    }
    _MEANINGS = {
        ("BOOKING", "reservation_status"): {"OK", "ELIGIBLE", "INVALID"},
        ("BOOKING", "payment_status"): {"PAID ONLINE", "ELIGIBLE", "UNPAID"},
        ("BANK", "transaction_type"): {"SALE", "REFUND", "CLOSURE", "IGNORE"},
    }

    def __init__(
        self,
        database: Database,
        audit: AuditService,
        booking: BookingCsvImportService,
        bank: BankFileImportService,
    ) -> None:
        self.database = database
        self.audit = audit
        self.booking = booking
        self.bank = bank

    def available_fields(self, quarantine_id: str) -> dict[str, str]:
        row = self._row(quarantine_id)
        return dict(self._FIELDS.get(str(row["run_type"]), {}))

    def available_meanings(self, quarantine_id: str, field_name: str) -> tuple[str, ...]:
        row = self._row(quarantine_id)
        source_kind = str(row["run_type"])
        if field_name not in self._FIELDS.get(source_kind, {}):
            raise QuarantineError("Pro tento karanténní řádek nelze zvolené pole mapovat.")
        return tuple(sorted(self._MEANINGS[(source_kind, field_name)]))

    def map_value(self, quarantine_id: str, field_name: str, mapped_meaning: str) -> str:
        row = self._row(quarantine_id)
        source_kind = str(row["run_type"])
        if field_name not in self._FIELDS.get(source_kind, {}):
            raise QuarantineError("Pro tento karanténní řádek nelze zvolené pole mapovat.")
        meaning = normalize_text(mapped_meaning).upper()
        if meaning not in self._MEANINGS[(source_kind, field_name)]:
            raise QuarantineError("Zvolený význam není pro toto pole podporovaný.")
        raw = json.loads(row["raw_json"])
        source_column = self._FIELDS[source_kind][field_name]
        raw_value = normalize_text(raw.get(source_column))
        if not raw_value:
            raise QuarantineError("Mapovaná hodnota je prázdná.")
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            previous = conn.execute(
                "SELECT mapped_meaning FROM import_value_mapping WHERE source_kind=? AND field_name=? AND raw_value=?",
                (source_kind, field_name, raw_value),
            ).fetchone()
            previous_state = str(row["state"])
            previous_resolution = row["resolution_json"]
            conn.execute(
                "INSERT INTO import_value_mapping(source_kind,field_name,raw_value,mapped_meaning,updated_at_utc) VALUES(?,?,?,?,?) "
                "ON CONFLICT(source_kind,field_name,raw_value) DO UPDATE SET mapped_meaning=excluded.mapped_meaning,updated_at_utc=excluded.updated_at_utc",
                (source_kind, field_name, raw_value, meaning, utc_now()),
            )
            resolution = {"field_name": field_name, "raw_value": raw_value, "mapped_meaning": meaning}
            conn.execute(
                "UPDATE quarantined_source_row SET state='READY_FOR_RETRY',resolution_method='MAPPED',resolution_json=?,resolved_at_utc=NULL,updated_at_utc=? WHERE id=?",
                (canonical_json(resolution), utc_now(), quarantine_id),
            )
            payload = {"quarantine_id": quarantine_id, "decision": resolution, "state": "READY_FOR_RETRY"}
            inverse = {
                "quarantine_id": quarantine_id,
                "source_kind": source_kind,
                "field_name": field_name,
                "raw_value": raw_value,
                "mapped_meaning": None if previous is None else previous["mapped_meaning"],
                "state": previous_state,
                "resolution_json": previous_resolution,
            }
            self._record_command(conn, command_id, correlation, "QUARANTINE_MAP", payload, inverse, "Namapování hodnoty karantény")
            self.audit.append(
                conn,
                event_code="QUARANTINE_VALUE_MAPPED",
                operation_label="Namapovat neznámou hodnotu",
                context=AuditContext(correlation, command_id),
                object_ref=f"QUARANTINE:{quarantine_id}",
                before={"state": previous_state, "mapping": None if previous is None else previous["mapped_meaning"]},
                after={"state": "READY_FOR_RETRY", "mapping": resolution},
            )
        return command_id

    def ignore(self, quarantine_id: str, note: str | None = None) -> str:
        row = self._row(quarantine_id)
        command_id = uuid4().hex
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            resolution = {"decision": "IGNORE", "note": note}
            conn.execute(
                "UPDATE quarantined_source_row SET state='IGNORED',resolution_method='USER_IGNORE',resolution_json=?,resolved_at_utc=?,updated_at_utc=? WHERE id=?",
                (canonical_json(resolution), utc_now(), utc_now(), quarantine_id),
            )
            self._record_command(
                conn,
                command_id,
                correlation,
                "QUARANTINE_IGNORE",
                {"quarantine_id": quarantine_id, "state": "IGNORED", "resolution_json": canonical_json(resolution)},
                {"quarantine_id": quarantine_id, "state": row["state"], "resolution_json": row["resolution_json"]},
                "Vědomé ignorování karanténního řádku",
            )
            self.audit.append(
                conn,
                event_code="QUARANTINE_IGNORED",
                operation_label="Vědomě ignorovat řádek",
                context=AuditContext(correlation, command_id),
                object_ref=f"QUARANTINE:{quarantine_id}",
                before={"state": row["state"]},
                after={"state": "IGNORED", "note": note},
            )
        return command_id

    def retry(self, quarantine_id: str) -> BookingImportReport | BankImportReport:
        row = self._row(quarantine_id)
        if row["state"] not in {"OPEN", "READY_FOR_RETRY"}:
            raise QuarantineError("Tento řádek není připravený k novému zpracování.")
        try:
            result = self.booking.reprocess_quarantine(quarantine_id) if row["run_type"] == "BOOKING" else self.bank.reprocess_quarantine(quarantine_id)
        except ImportValidationError as exc:
            raise QuarantineError(str(exc)) from exc
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            self.audit.append(
                conn,
                event_code="QUARANTINE_REPROCESSED",
                operation_label="Znovu zpracovat karanténní řádek",
                context=AuditContext(correlation),
                object_ref=f"QUARANTINE:{quarantine_id}",
                before={"state": row["state"]},
                after={"state": "RESOLVED", "new_rows": result.new_rows, "duplicate_rows": result.duplicate_rows},
            )
        return result

    def undo(self, command_id: str) -> str:
        with self.database.transaction() as conn:
            command = conn.execute("SELECT * FROM action_command WHERE command_id=? AND state='APPLIED'", (command_id,)).fetchone()
            if command is None or command["command_type"] not in {"QUARANTINE_MAP", "QUARANTINE_IGNORE"}:
                raise QuarantineError("Toto karanténní rozhodnutí nelze vrátit.")
            inverse = json.loads(command["inverse_payload_json"])
            if command["command_type"] == "QUARANTINE_MAP":
                if inverse["mapped_meaning"] is None:
                    conn.execute(
                        "DELETE FROM import_value_mapping WHERE source_kind=? AND field_name=? AND raw_value=?",
                        (inverse["source_kind"], inverse["field_name"], inverse["raw_value"]),
                    )
                else:
                    conn.execute(
                        "UPDATE import_value_mapping SET mapped_meaning=?,updated_at_utc=? WHERE source_kind=? AND field_name=? AND raw_value=?",
                        (inverse["mapped_meaning"], utc_now(), inverse["source_kind"], inverse["field_name"], inverse["raw_value"]),
                    )
            conn.execute(
                "UPDATE quarantined_source_row SET state=?,resolution_json=?,resolution_method=NULL,resolved_at_utc=NULL,updated_at_utc=? WHERE id=?",
                (inverse["state"], inverse.get("resolution_json"), utc_now(), inverse["quarantine_id"]),
            )
            undo_id = uuid4().hex
            correlation = uuid4().hex
            now = utc_now()
            conn.execute("UPDATE action_command SET state='REVERSED',reversed_at_utc=? WHERE command_id=?", (now, command_id))
            self._record_command(conn, undo_id, correlation, "UNDO", {"original_command_id": command_id}, {"original_command_id": command_id}, f"Vrátit: {command['human_label']}")
            self.audit.append(conn, event_code="COMMAND_UNDO", operation_label=f"Vrátit: {command['human_label']}", context=AuditContext(correlation, undo_id), object_ref=f"COMMAND:{command_id}", before={"state": "APPLIED"}, after={"state": "REVERSED"})
            return undo_id

    def redo(self, command_id: str) -> str:
        with self.database.transaction() as conn:
            command = conn.execute("SELECT * FROM action_command WHERE command_id=? AND state='REVERSED'", (command_id,)).fetchone()
            if command is None or command["command_type"] not in {"QUARANTINE_MAP", "QUARANTINE_IGNORE"}:
                raise QuarantineError("Toto karanténní rozhodnutí nelze znovu provést.")
            payload = json.loads(command["payload_json"])
            if command["command_type"] == "QUARANTINE_MAP":
                decision = payload["decision"]
                row = conn.execute("SELECT run_type FROM quarantined_source_row WHERE id=?", (payload["quarantine_id"],)).fetchone()
                conn.execute(
                    "INSERT INTO import_value_mapping(source_kind,field_name,raw_value,mapped_meaning,updated_at_utc) VALUES(?,?,?,?,?) ON CONFLICT(source_kind,field_name,raw_value) DO UPDATE SET mapped_meaning=excluded.mapped_meaning,updated_at_utc=excluded.updated_at_utc",
                    (row["run_type"], decision["field_name"], decision["raw_value"], decision["mapped_meaning"], utc_now()),
                )
                resolution_method = "MAPPED"
                resolved_at = None
            else:
                resolution_method = "USER_IGNORE"
                resolved_at = utc_now()
            conn.execute(
                "UPDATE quarantined_source_row SET state=?,resolution_json=?,resolution_method=?,resolved_at_utc=?,updated_at_utc=? WHERE id=?",
                (payload["state"], payload.get("resolution_json") or canonical_json(payload.get("decision", {})), resolution_method, resolved_at, utc_now(), payload["quarantine_id"]),
            )
            redo_id = uuid4().hex
            correlation = uuid4().hex
            now = utc_now()
            conn.execute("UPDATE action_command SET state='APPLIED',applied_at_utc=?,reversed_at_utc=NULL WHERE command_id=?", (now, command_id))
            self._record_command(conn, redo_id, correlation, "REDO", {"original_command_id": command_id}, {"original_command_id": command_id}, f"Znovu: {command['human_label']}")
            self.audit.append(conn, event_code="COMMAND_REDO", operation_label=f"Znovu: {command['human_label']}", context=AuditContext(correlation, redo_id), object_ref=f"COMMAND:{command_id}", before={"state": "REVERSED"}, after={"state": "APPLIED"})
            return redo_id

    def _row(self, quarantine_id: str) -> Any:
        rows = self.database.query("SELECT * FROM quarantined_source_row WHERE id=?", (quarantine_id,))
        if not rows:
            raise QuarantineError("Karanténní řádek neexistuje.")
        return rows[0]

    @staticmethod
    def _record_command(conn: Any, command_id: str, correlation: str, command_type: str, payload: dict[str, Any], inverse: dict[str, Any], label: str) -> None:
        now = utc_now()
        conn.execute(
            "INSERT INTO action_command(command_id,correlation_id,command_type,payload_json,inverse_payload_json,human_label,reversible,state,created_at_utc,applied_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (command_id, correlation, command_type, canonical_json(payload), canonical_json(inverse), label, 1, "APPLIED", now, now),
        )
