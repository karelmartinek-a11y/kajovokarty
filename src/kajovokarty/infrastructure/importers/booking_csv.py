from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...domain.entities import BookingPaymentLine
from ...domain.enums import MatchStatus, RunState
from ..persistence.database import Database
from .common import (
    CancelCallback,
    ImportCancelled,
    ImportValidationError,
    ProgressCallback,
    canonical_json,
    cancellation_point,
    immutable_snapshot,
    map_headers,
    money_minor,
    normalize_text,
    parse_czech_date,
    progress,
    row_dict,
    sha256_text,
    utc_now,
)

BOOKING_HEADERS = (
    "Typ faktury",
    "Číslo rezervace",
    "Datum příjezdu",
    "Checkout",
    "Jméno hosta",
    "Poskytovatel platebních služeb",
    "Status rezervace",
    "Měna",
    "Status platby",
    "Částka",
    "Datum vyplacení částky",
    "ID platby",
)


@dataclass(slots=True)
class BookingImportReport:
    run_id: str
    correlation_id: str
    file_hash: str
    new_rows: int = 0
    duplicate_rows: int = 0
    conflicts: int = 0
    quarantined: int = 0
    ignored: int = 0
    totals_minor: dict[str, int] = field(default_factory=dict)
    status_counts: Counter[str] = field(default_factory=Counter)
    rows_seen: int = 0
    state: RunState = RunState.PENDING
    messages: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ParsedBookingRow:
    line: BookingPaymentLine
    raw: dict[str, object]
    natural_key: str
    batch_hash: str
    source_identity: str
    eligible: bool
    quarantine_reason: str | None


class BookingCsvImportService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def inspect(self, path: Path) -> list[ParsedBookingRow]:
        snapshot = immutable_snapshot(path)
        try:
            return self._parse_file(snapshot.snapshot_path, self._load_mappings())
        finally:
            snapshot.cleanup()

    def import_file(
        self,
        path: Path,
        *,
        progress_callback: ProgressCallback | None = None,
        cancel_callback: CancelCallback | None = None,
        correlation_id: str | None = None,
    ) -> BookingImportReport:
        snapshot = immutable_snapshot(path)
        run_id = uuid4().hex
        correlation = correlation_id or uuid4().hex
        report = BookingImportReport(run_id, correlation, snapshot.file_hash, state=RunState.RUNNING)
        started = utc_now()
        try:
            previous = self.database.query(
                "SELECT counts_json,totals_json FROM booking_import_run WHERE file_hash=? AND state IN ('SUCCEEDED','DUPLICATE') ORDER BY finished_at_utc DESC LIMIT 1",
                (snapshot.file_hash,),
            )
            if previous:
                counts = json.loads(previous[0]["counts_json"] or "{}")
                report.rows_seen = int(counts.get("seen", 0))
                report.duplicate_rows = report.rows_seen
                report.totals_minor = {str(key): int(value) for key, value in json.loads(previous[0]["totals_json"] or "{}").items()}
                report.state = RunState.DUPLICATE
                report.messages.append("Přesný duplikát souboru byl bezpečně přeskočen.")
                self._record_completed_run(path, report, started)
                return report
            rows = self._parse_file(snapshot.snapshot_path, self._load_mappings())
            report.rows_seen = len(rows)
            total = len(rows)
            # Do not invoke the operation progress callback while this write
            # transaction is open. The UI callback persists operation state via
            # a second SQLite connection, which would otherwise deadlock here.
            progress(progress_callback, 0, total, f"Booking.com: připravuji {total} řádků")
            with self.database.transaction() as conn:
                conn.execute(
                    "INSERT INTO booking_import_run(id,correlation_id,file_name,file_hash,state,counts_json,totals_json,started_at_utc,heartbeat_at_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                    (run_id, correlation, path.name, snapshot.file_hash, RunState.RUNNING.value, "{}", "{}", started, started),
                )
                for index, parsed in enumerate(rows, start=1):
                    cancellation_point(cancel_callback)
                    self._apply_row(conn, run_id, parsed, report)
                    if index % 20 == 0:
                        conn.execute("UPDATE booking_import_run SET heartbeat_at_utc=? WHERE id=?", (utc_now(), run_id))
                report.state = RunState.SUCCEEDED
                conn.execute(
                    "UPDATE booking_import_run SET state=?,counts_json=?,totals_json=?,heartbeat_at_utc=?,finished_at_utc=? WHERE id=?",
                    (report.state.value, canonical_json(self._counts(report)), canonical_json(report.totals_minor), utc_now(), utc_now(), run_id),
                )
            progress(progress_callback, total, total, f"Booking.com: hotovo, {total} řádků")
            return report
        except ImportCancelled:
            report.state = RunState.CANCELLED
            self._record_failed_run(path, snapshot.file_hash, report, started, "cancelled")
            raise
        except Exception as exc:
            report.state = RunState.FAILED
            self._record_failed_run(path, snapshot.file_hash, report, started, str(exc))
            raise
        finally:
            snapshot.cleanup()

    def reprocess_quarantine(self, quarantine_id: str) -> BookingImportReport:
        rows = self.database.query("SELECT * FROM quarantined_source_row WHERE id=? AND run_type='BOOKING'", (quarantine_id,))
        if not rows:
            raise ImportValidationError("Karanténní řádek Booking.com neexistuje.")
        quarantine = rows[0]
        raw = json.loads(quarantine["raw_json"])
        parsed = self._parse_row(raw, self._load_mappings())
        if not parsed.eligible:
            self.database.execute("UPDATE quarantined_source_row SET retry_count=retry_count+1,updated_at_utc=? WHERE id=?", (utc_now(), quarantine_id))
            raise ImportValidationError("Řádek stále nemá bezpečně namapovaný status.")
        report = BookingImportReport(str(quarantine["run_id"]), uuid4().hex, "reprocess", rows_seen=1, state=RunState.RUNNING)
        with self.database.transaction() as conn:
            self._apply_row(conn, str(quarantine["run_id"]), parsed, report)
            if report.quarantined or report.conflicts:
                conn.execute("UPDATE quarantined_source_row SET retry_count=retry_count+1,updated_at_utc=? WHERE id=?", (utc_now(), quarantine_id))
                raise ImportValidationError("Řádek nelze bezpečně znovu zpracovat; vznikl konflikt.")
            conn.execute(
                "UPDATE quarantined_source_row SET state='RESOLVED',resolution_method='REPROCESSED',resolution_json=?,resolved_at_utc=?,updated_at_utc=?,retry_count=retry_count+1 WHERE id=?",
                (canonical_json({"new": report.new_rows, "duplicate": report.duplicate_rows}), utc_now(), utc_now(), quarantine_id),
            )
        report.state = RunState.SUCCEEDED
        return report

    def _record_completed_run(self, path: Path, report: BookingImportReport, started: str) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO booking_import_run(id,correlation_id,file_name,file_hash,state,counts_json,totals_json,error_json,started_at_utc,heartbeat_at_utc,finished_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (report.run_id, report.correlation_id, path.name, report.file_hash, report.state.value, canonical_json(self._counts(report)), canonical_json(report.totals_minor), None, started, utc_now(), utc_now()),
            )

    def _record_failed_run(self, path: Path, file_hash: str, report: BookingImportReport, started: str, error: str) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO booking_import_run(id,correlation_id,file_name,file_hash,state,counts_json,totals_json,error_json,started_at_utc,heartbeat_at_utc,finished_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET state=excluded.state,error_json=excluded.error_json,heartbeat_at_utc=excluded.heartbeat_at_utc,finished_at_utc=excluded.finished_at_utc",
                (report.run_id, report.correlation_id, path.name, file_hash, report.state.value, canonical_json(self._counts(report)), canonical_json(report.totals_minor), canonical_json({"message": error}), started, utc_now(), utc_now()),
            )

    @staticmethod
    def _counts(report: BookingImportReport) -> dict[str, int]:
        return {"seen": report.rows_seen, "new": report.new_rows, "duplicate": report.duplicate_rows, "conflict": report.conflicts, "quarantine": report.quarantined, "ignored": report.ignored}

    def _load_mappings(self) -> dict[tuple[str, str], str]:
        return {
            (str(row["field_name"]), normalize_text(row["raw_value"]).casefold()): str(row["mapped_meaning"])
            for row in self.database.query("SELECT field_name,raw_value,mapped_meaning FROM import_value_mapping WHERE source_kind='BOOKING'")
        }

    def _parse_file(self, path: Path, mappings: dict[tuple[str, str], str]) -> list[ParsedBookingRow]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, dialect="excel", strict=True)
            try:
                headers = next(reader)
            except StopIteration as exc:
                raise ImportValidationError("Booking.com CSV je prázdné.") from exc
            mapping = map_headers(headers, BOOKING_HEADERS)
            parsed: list[ParsedBookingRow] = []
            for row_no, row in enumerate(reader, start=2):
                if not any(normalize_text(cell) for cell in row):
                    continue
                raw = row_dict(row, mapping)
                raw["_row_no"] = row_no
                try:
                    parsed.append(self._parse_row(raw, mappings))
                except ImportValidationError as exc:
                    parsed.append(self._quarantine_parse_failure(raw, row_no, str(exc)))
            return parsed

    def _parse_row(self, raw: dict[str, object], mappings: dict[tuple[str, str], str] | None = None) -> ParsedBookingRow:
        mappings = mappings or {}
        reservation = normalize_text(raw["Číslo rezervace"])
        payment_id = normalize_text(raw["ID platby"])
        if not reservation:
            raise ImportValidationError("Číslo rezervace chybí.")
        if not payment_id:
            raise ImportValidationError("ID platby chybí.")
        arrival = parse_czech_date(raw["Datum příjezdu"], allow_empty=True)
        departure = parse_czech_date(raw["Checkout"], allow_empty=True)
        payout_date = parse_czech_date(raw["Datum vyplacení částky"])
        assert payout_date is not None
        amount_minor, currency = money_minor(raw["Částka"], raw["Měna"])
        reservation_status = normalize_text(raw["Status rezervace"])
        payment_status = normalize_text(raw["Status platby"])
        effective_reservation = mappings.get(("reservation_status", reservation_status.casefold()), reservation_status)
        effective_payment = mappings.get(("payment_status", payment_status.casefold()), payment_status)
        reservation_ok = normalize_text(effective_reservation).casefold() in {"ok", "eligible", "valid", "platna", "platná"}
        payment_ok = normalize_text(effective_payment).casefold() in {"paid online", "eligible", "paid", "uhrazeno online"}
        natural_key = sha256_text(payment_id, payout_date.isoformat(), currency)
        row_hash = sha256_text(payment_id, reservation, currency, amount_minor, payout_date.isoformat(), arrival.isoformat() if arrival else "", departure.isoformat() if departure else "", raw["Typ faktury"], payment_status)
        source_identity = sha256_text(payment_id, reservation, currency, payout_date.isoformat(), raw["Typ faktury"])
        content_hash = sha256_text(canonical_json({key: value for key, value in raw.items() if not str(key).startswith("_")}))
        eligible = reservation_ok and payment_ok and amount_minor != 0
        reason = None if eligible else ("ZERO_AMOUNT" if amount_minor == 0 else "BOOKING_UNKNOWN_STATUS")
        line = BookingPaymentLine(
            row_hash=row_hash,
            batch_natural_key=natural_key,
            payment_id=payment_id,
            booking_reference=reservation,
            amount_minor=amount_minor,
            currency=currency,
            payout_date=payout_date,
            arrival=arrival,
            departure=departure,
            reservation_status=reservation_status,
            payment_status=payment_status,
            guest_name=normalize_text(raw["Jméno hosta"]) or None,
            status=MatchStatus.UNMATCHED if eligible else MatchStatus.CONFLICT,
            content_hash=content_hash,
        )
        batch_hash = sha256_text(natural_key, payment_id, payout_date.isoformat(), currency)
        return ParsedBookingRow(line, raw, natural_key, batch_hash, source_identity, eligible, reason)

    def _quarantine_parse_failure(self, raw: dict[str, object], row_no: int, message: str) -> ParsedBookingRow:
        raw_with_error = dict(raw)
        raw_with_error["_row_no"] = row_no
        raw_with_error["_parse_error"] = message
        row_hash = sha256_text("invalid", row_no, canonical_json(raw_with_error))
        fallback_date = parse_czech_date("01.01.1970")
        assert fallback_date is not None
        line = BookingPaymentLine(
            row_hash=row_hash,
            batch_natural_key=sha256_text("invalid-batch", row_no),
            payment_id=normalize_text(raw.get("ID platby")) or f"INVALID-{row_no}",
            booking_reference=normalize_text(raw.get("Číslo rezervace")) or f"INVALID-{row_no}",
            amount_minor=0,
            currency="EUR",
            payout_date=fallback_date,
            arrival=None,
            departure=None,
            reservation_status=normalize_text(raw.get("Status rezervace")),
            payment_status=normalize_text(raw.get("Status platby")),
            status=MatchStatus.CONFLICT,
            content_hash=sha256_text(canonical_json(raw_with_error)),
        )
        return ParsedBookingRow(line, raw_with_error, line.batch_natural_key, line.content_hash, sha256_text("invalid-source", row_no), False, "ROW_PARSE_ERROR")

    def _apply_row(self, conn: Any, run_id: str, parsed: ParsedBookingRow, report: BookingImportReport) -> None:
        line = parsed.line
        existing = conn.execute("SELECT row_hash,content_hash,last_seen_utc FROM booking_payment_line WHERE row_hash=?", (line.row_hash,)).fetchone()
        if existing is not None:
            if existing["content_hash"] == line.content_hash:
                report.duplicate_rows += 1
                conn.execute("UPDATE booking_payment_line SET last_seen_utc=? WHERE row_hash=?", (utc_now(), line.row_hash))
                return
            report.conflicts += 1
            self._quarantine(conn, run_id, parsed, "ROW_HASH_CONTENT_CONFLICT")
            return

        batch = conn.execute("SELECT id,content_hash FROM booking_payout_batch WHERE natural_key=?", (parsed.natural_key,)).fetchone()
        if batch is not None and batch["content_hash"] != parsed.batch_hash:
            report.conflicts += 1
            self._quarantine(conn, run_id, parsed, "PAYOUT_NATURAL_KEY_CONFLICT")
            return
        batch_id = batch["id"] if batch is not None else uuid4().hex
        now = utc_now()
        if batch is None:
            conn.execute("INSERT INTO booking_payout_batch(id,natural_key,payment_id,payout_date,currency_code,content_hash,first_seen_utc,last_seen_utc) VALUES(?,?,?,?,?,?,?,?)", (batch_id, parsed.natural_key, line.payment_id, line.payout_date.isoformat(), line.currency, parsed.batch_hash, now, now))
        else:
            conn.execute("UPDATE booking_payout_batch SET last_seen_utc=? WHERE id=?", (now, batch_id))
        if not parsed.eligible:
            report.quarantined += 1
            self._quarantine(conn, run_id, parsed, parsed.quarantine_reason or "UNKNOWN")
            return

        previous = conn.execute("SELECT * FROM booking_payment_line WHERE source_identity=? AND active_source=1 ORDER BY last_seen_utc DESC LIMIT 1", (parsed.source_identity,)).fetchone()
        conn.execute(
            "INSERT INTO booking_payment_line(row_hash,batch_id,booking_reference,amount_minor,currency_code,arrival,departure,guest_name,provider,reservation_status,payment_status,status,raw_json,content_hash,first_seen_utc,last_seen_utc,row_version,payout_date,source_identity,active_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,1)",
            (line.row_hash, batch_id, line.booking_reference, line.amount_minor, line.currency, line.arrival.isoformat() if line.arrival else None, line.departure.isoformat() if line.departure else None, line.guest_name, normalize_text(parsed.raw.get("Poskytovatel platebních služeb")) or None, line.reservation_status, line.payment_status, line.status.value, canonical_json(parsed.raw), line.content_hash, now, now, line.payout_date.isoformat(), parsed.source_identity),
        )
        if previous is not None and previous["row_hash"] != line.row_hash:
            changed_fields = [field for field in ("amount_minor", "currency_code", "arrival", "departure", "reservation_status", "payment_status") if previous[field] != conn.execute(f"SELECT {field} FROM booking_payment_line WHERE row_hash=?", (line.row_hash,)).fetchone()[0]]
            conn.execute("UPDATE booking_payment_line SET active_source=0,status='REVIEW_REQUIRED',row_version=row_version+1,last_seen_utc=? WHERE row_hash=?", (now, previous["row_hash"]))
            conn.execute("INSERT INTO booking_line_revision(id,source_identity,previous_row_hash,current_row_hash,changed_fields_json,detected_at_utc) VALUES(?,?,?,?,?,?)", (uuid4().hex, parsed.source_identity, previous["row_hash"], line.row_hash, canonical_json(changed_fields), now))
            self._flag_revision(conn, previous["row_hash"], previous["content_hash"], line.content_hash, changed_fields)
            report.conflicts += 1
            report.messages.append(f"Zdrojový řádek {line.booking_reference} byl opraven; původní verze zůstala v historii.")
        report.new_rows += 1
        report.totals_minor[line.currency] = report.totals_minor.get(line.currency, 0) + line.amount_minor
        report.status_counts.update([f"{line.reservation_status}/{line.payment_status}"])

    @staticmethod
    def _quarantine(conn: Any, run_id: str, parsed: ParsedBookingRow, reason: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO quarantined_source_row(id,run_type,run_id,row_no,raw_json,reason_code,reason_text,resolution_json,state,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (uuid4().hex, "BOOKING", run_id, int(parsed.raw.get("_row_no", 0) or 0), canonical_json(parsed.raw), reason, reason, None, "OPEN", utc_now(), utc_now()),
        )

    @staticmethod
    def _flag_revision(conn: Any, old_row_hash: str, old_hash: str, new_hash: str, changed_fields: list[str]) -> None:
        affected = [row[0] for row in conn.execute("SELECT DISTINCT group_id FROM match_group_source WHERE entity_type='BOOKING' AND entity_id=? AND active=1", (old_row_hash,)).fetchall()]
        if not affected:
            return
        now = utc_now()
        conn.execute("INSERT INTO source_revision_alert(id,object_ref,previous_hash,current_hash,changed_fields_json,affected_group_ids_json,state,detected_at_utc) VALUES(?,?,?,?,?,?,?,?)", (uuid4().hex, f"BOOKING:{old_row_hash}", old_hash, new_hash, canonical_json(changed_fields), canonical_json(affected), "OPEN", now))
        placeholders = ",".join("?" for _ in affected)
        conn.execute(f"UPDATE match_group SET status='REVIEW_REQUIRED',review_required_reason='Zdrojový řádek Booking.com se změnil',row_version=row_version+1,updated_at_utc=? WHERE id IN ({placeholders})", (now, *affected))
