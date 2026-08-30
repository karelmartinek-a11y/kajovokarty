from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from .audit import AuditContext, AuditService
from ..infrastructure.importers.common import utc_now
from ..infrastructure.persistence.database import Database


@dataclass(frozen=True, slots=True)
class ReferenceResolution:
    command_id: str
    reservation_id: str
    candidate: str
    status: str


class BookingReferenceResolutionService:
    """Audited and reversible manual resolution of Booking reference conflicts."""

    def __init__(self, database: Database, audit: AuditService) -> None:
        self.database = database
        self.audit = audit

    def confirm(self, extraction_id: str) -> ReferenceResolution:
        return self._apply(extraction_id, accept=True)

    def reject(self, extraction_id: str) -> ReferenceResolution:
        return self._apply(extraction_id, accept=False)

    def _apply(self, extraction_id: str, *, accept: bool) -> ReferenceResolution:
        command_id = uuid4().hex
        correlation_id = uuid4().hex
        now = utc_now()
        with self.database.transaction() as conn:
            extraction = conn.execute(
                "SELECT * FROM booking_reference_extraction WHERE id=?", (extraction_id,)
            ).fetchone()
            if extraction is None:
                raise ValueError("Booking reference nebyla nalezena.")
            reservation = conn.execute(
                "SELECT uuid,booking_reference,reference_status,row_version FROM reservation WHERE uuid=?",
                (extraction["reservation_id"],),
            ).fetchone()
            if reservation is None:
                raise ValueError("Rezervace k Booking reference nebyla nalezena.")
            before = {
                "reservation": dict(reservation),
                "extractions": [
                    dict(row)
                    for row in conn.execute(
                        "SELECT id,status FROM booking_reference_extraction WHERE reservation_id=? ORDER BY id",
                        (extraction["reservation_id"],),
                    )
                ],
            }
            if accept:
                conn.execute(
                    "UPDATE booking_reference_extraction SET status=CASE WHEN id=? THEN 'MANUAL_CONFIRMED' "
                    "ELSE 'MANUAL_REJECTED' END WHERE reservation_id=?",
                    (extraction_id, extraction["reservation_id"]),
                )
                new_reference: str | None = str(extraction["candidate"])
                new_status = "MANUAL_CONFIRMED"
                label = "Potvrzení Booking reference"
                event_code = "BOOKING_REFERENCE_CONFIRMED"
            else:
                conn.execute(
                    "UPDATE booking_reference_extraction SET status='MANUAL_REJECTED' WHERE id=?",
                    (extraction_id,),
                )
                remaining = conn.execute(
                    "SELECT DISTINCT candidate FROM booking_reference_extraction WHERE reservation_id=? "
                    "AND status NOT IN ('MANUAL_REJECTED','REJECTED') ORDER BY candidate",
                    (extraction["reservation_id"],),
                ).fetchall()
                if len(remaining) == 1:
                    new_reference = str(remaining[0][0])
                    new_status = "MANUAL_CONFIRMED"
                elif len(remaining) > 1:
                    new_reference = None
                    new_status = "CONFLICT"
                else:
                    new_reference = None
                    new_status = "MISSING"
                label = "Odmítnutí Booking reference"
                event_code = "BOOKING_REFERENCE_REJECTED"
            conn.execute(
                "UPDATE reservation SET booking_reference=?,reference_status=?,row_version=row_version+1 WHERE uuid=?",
                (new_reference, new_status, extraction["reservation_id"]),
            )
            after_reservation = conn.execute(
                "SELECT uuid,booking_reference,reference_status,row_version FROM reservation WHERE uuid=?",
                (extraction["reservation_id"],),
            ).fetchone()
            after = {
                "reservation": dict(after_reservation),
                "extractions": [
                    dict(row)
                    for row in conn.execute(
                        "SELECT id,status FROM booking_reference_extraction WHERE reservation_id=? ORDER BY id",
                        (extraction["reservation_id"],),
                    )
                ],
            }
            payload = {
                "extraction_id": extraction_id,
                "reservation_id": extraction["reservation_id"],
                "candidate": extraction["candidate"],
                "accept": accept,
                "after": after,
            }
            inverse = {"before": before}
            conn.execute(
                "INSERT INTO action_command(command_id,correlation_id,command_type,payload_json,inverse_payload_json,"
                "human_label,reversible,state,created_at_utc,applied_at_utc) VALUES(?,?,?,?,?,?,1,'APPLIED',?,?)",
                (
                    command_id,
                    correlation_id,
                    "BOOKING_REFERENCE_CONFIRM" if accept else "BOOKING_REFERENCE_REJECT",
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    json.dumps(inverse, ensure_ascii=False, sort_keys=True),
                    label,
                    now,
                    now,
                ),
            )
            self.audit.append(
                conn,
                event_code=event_code,
                operation_label=label,
                context=AuditContext(correlation_id, command_id),
                object_ref=f"BOOKING_REFERENCE:{extraction_id}",
                before=before,
                after=after,
                redacted_context={"reservation_id": extraction["reservation_id"]},
            )
        return ReferenceResolution(command_id, str(extraction["reservation_id"]), str(extraction["candidate"]), new_status)

    def undo(self, command_id: str) -> None:
        with self.database.transaction() as conn:
            command = conn.execute(
                "SELECT * FROM action_command WHERE command_id=? AND command_type IN "
                "('BOOKING_REFERENCE_CONFIRM','BOOKING_REFERENCE_REJECT')",
                (command_id,),
            ).fetchone()
            if command is None or command["state"] != "APPLIED":
                raise ValueError("Tuto změnu Booking reference nelze vrátit.")
            inverse = json.loads(command["inverse_payload_json"] or "{}")
            before = inverse.get("before") or {}
            reservation = before.get("reservation") or {}
            if not reservation:
                raise ValueError("Kompenzační data Booking reference nejsou úplná.")
            conn.execute(
                "UPDATE reservation SET booking_reference=?,reference_status=?,row_version=row_version+1 WHERE uuid=?",
                (
                    reservation.get("booking_reference"),
                    reservation.get("reference_status"),
                    reservation["uuid"],
                ),
            )
            for item in before.get("extractions", []):
                conn.execute(
                    "UPDATE booking_reference_extraction SET status=? WHERE id=?",
                    (item["status"], item["id"]),
                )
            now = utc_now()
            conn.execute(
                "UPDATE action_command SET state='REVERSED',reversed_at_utc=? WHERE command_id=?",
                (now, command_id),
            )
            self.audit.append(
                conn,
                event_code="BOOKING_REFERENCE_UNDO",
                operation_label=f"Vrátit: {command['human_label']}",
                context=AuditContext(command["correlation_id"], command_id),
                object_ref=f"RESERVATION:{reservation['uuid']}",
                before=json.loads(command["payload_json"]),
                after=before,
            )

    def redo(self, command_id: str) -> None:
        row = self.database.query(
            "SELECT payload_json,state FROM action_command WHERE command_id=? AND command_type IN "
            "('BOOKING_REFERENCE_CONFIRM','BOOKING_REFERENCE_REJECT')",
            (command_id,),
        )
        if not row or row[0]["state"] != "REVERSED":
            raise ValueError("Tuto změnu Booking reference nelze znovu provést.")
        payload = json.loads(row[0]["payload_json"])
        # Redo is deliberately a new audited command; history remains append-only.
        self._apply(str(payload["extraction_id"]), accept=bool(payload["accept"]))
