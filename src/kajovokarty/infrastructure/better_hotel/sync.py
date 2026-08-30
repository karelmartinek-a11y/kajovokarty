from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from ...domain.reference_parser import ReservationReferenceParser
from ..importers.common import canonical_json, utc_now
from ..persistence.database import Database
from .client import BetterHotelCancelled, BetterHotelClient
from .dto import (
    BetterHotelDataError,
    InvoiceDTO,
    ReservationDTO,
    amount_minor,
    as_int,
    content_hash,
    currency_code,
)

ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]
_RESOURCE_KEYS = (
    "currency",
    "invoice",
    "invoice_item",
    "reservation",
    "bill",
    "bill_item",
    "security_deposit",
    "financial_stats",
)


@dataclass(slots=True)
class SyncReport:
    run_id: str
    correlation_id: str
    inserted: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_RESOURCE_KEYS, 0))
    updated: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_RESOURCE_KEYS, 0))
    unchanged: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_RESOURCE_KEYS, 0))
    diagnostics: list[str] = field(default_factory=list)
    state: str = "RUNNING"


class BetterHotelSyncService:
    """Read-only, checkpointed Better Hotel synchronization.

    Network reads are deliberately completed before each short SQLite write transaction.
    That keeps the UI worker cancellable and prevents a slow HTTP request from holding a
    database write lock.
    """

    def __init__(self, database: Database, parser: ReservationReferenceParser | None = None) -> None:
        self.database = database
        self.parser = parser or ReservationReferenceParser()

    def sync(
        self,
        client: BetterHotelClient,
        *,
        first_day: date,
        block_days: int = 7,
        overlap_hours: int = 48,
        progress: ProgressCallback | None = None,
        cancel: CancelCallback | None = None,
        correlation_id: str | None = None,
        modified_since: str | None = None,
        include_extended_reservation_details: bool = True,
    ) -> SyncReport:
        if not 1 <= block_days <= 31:
            raise ValueError("Délka historického bloku musí být 1 až 31 dní.")
        if not 0 <= overlap_hours <= 168:
            raise ValueError("Překryv musí být 0 až 168 hodin.")
        run_id = uuid4().hex
        correlation = correlation_id or uuid4().hex
        report = SyncReport(run_id, correlation)
        started = utc_now()
        today = date.today()
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO api_sync_run(id,correlation_id,state,range_start,range_end,counts_json,started_at_utc,heartbeat_at_utc) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, correlation, "RUNNING", first_day.isoformat(), today.isoformat(), "{}", started, started),
            )
        headers = {"X-Modified": modified_since} if modified_since else None
        try:
            currencies = self._sync_currencies(client, report, cancel, correlation)
            blocks = list(_date_blocks(first_day, today, block_days))
            if progress:
                progress(0, 1, f"Připravuji {len(blocks)} historických bloků; načítám první stránku")
            for start, end in blocks:
                self._cancel_point(cancel)
                self._sync_invoices_block(client, currencies, start, end, report, cancel, headers, progress)
                self._checkpoint("invoice", end, overlap_hours)

                self._sync_reservations_block(client, currencies, start, end, report, cancel, headers, progress, include_extended_reservation_details)
                self._checkpoint("reservation", end, overlap_hours)
                self._heartbeat(run_id)

            self._sync_financial_stats(client, first_day, today, report, cancel, correlation)
            if progress:
                progress(1, 1, "Doplňková finanční diagnostika dokončena")
            report.state = "SUCCEEDED"
            self._finish_run(report, None)
            return report
        except BetterHotelCancelled:
            report.state = "CANCELLED"
            self._finish_run(report, "Operace byla bezpečně zrušena.")
            raise
        except Exception as exc:
            report.state = "FAILED"
            self._finish_run(report, str(exc))
            raise

    def refresh_object(
        self,
        client: BetterHotelClient,
        *,
        object_type: str,
        object_id: str,
        progress: ProgressCallback | None = None,
        cancel: CancelCallback | None = None,
        correlation_id: str | None = None,
    ) -> SyncReport:
        """Refresh one API-backed object using read-only GET requests.

        The fetched snapshot is persisted through the same revision-aware code path as a
        normal synchronization. A meta-only or empty detail never erases an existing
        object. Booking-reference refresh is routed to its reservation by the UI.
        """
        normalized_type = object_type.strip().upper()
        supported = {"INVOICE", "RESERVATION", "BILL", "BILL_ITEM"}
        if normalized_type not in supported:
            raise ValueError("Aktuální stav lze načíst pouze pro doklad, rezervaci, účet nebo položku účtu.")
        run_id = uuid4().hex
        correlation = correlation_id or uuid4().hex
        report = SyncReport(run_id, correlation)
        currencies = {"CZK": "CZK", "EUR": "EUR"}
        currency_rows = self.database.query("SELECT external_id,iso_code FROM currency")
        if currency_rows:
            for row in currency_rows:
                currencies[str(row["external_id"])] = str(row["iso_code"])
        else:
            currencies = self._sync_currencies(client, report, cancel, correlation)
        self._cancel_point(cancel)
        if progress:
            progress(0, 1, "Načítám aktuální read-only detail")

        if normalized_type == "INVOICE":
            endpoint = f"/invoice/{object_id}"
            payload = client.get(endpoint, cancel=cancel)
            raw = _single_record(payload)
            with self.database.transaction() as conn:
                self._store_snapshot(conn, "invoice-detail", object_id, endpoint, payload, correlation)
                if raw:
                    dto = InvoiceDTO.from_payload(_merge_snapshot({"id": object_id}, raw), currencies)
                    self._persist_invoice(conn, dto, report)
                    self._persist_invoice_items(
                        conn,
                        dto,
                        _embedded_items(raw, ("invoice_item", "invoice_items", "items")),
                        currencies,
                        report,
                    )
                elif conn.execute("SELECT 1 FROM invoice WHERE external_id=?", (object_id,)).fetchone() is None:
                    raise BetterHotelDataError("Better Hotel nevrátil detail požadovaného dokladu.")
                else:
                    report.diagnostics.append(
                        "Detail dokladu obsahoval pouze metadata; uložený objekt zůstal beze změny."
                    )
                    report.unchanged["invoice"] += 1
        elif normalized_type == "RESERVATION":
            endpoint = f"/reservation/{object_id}"
            payload = client.get(
                endpoint,
                params={"expand[]": ["reservation_source", "reservation_note"]},
                cancel=cancel,
            )
            raw = _single_record(payload)
            if not raw:
                with self.database.transaction() as conn:
                    self._store_snapshot(conn, "reservation-detail", object_id, endpoint, payload, correlation)
                    if conn.execute("SELECT 1 FROM reservation WHERE uuid=?", (object_id,)).fetchone() is None:
                        raise BetterHotelDataError("Better Hotel nevrátil detail požadované rezervace.")
                    report.diagnostics.append(
                        "Detail rezervace obsahoval pouze metadata; uložený objekt zůstal beze změny."
                    )
                    report.unchanged["reservation"] += 1
            else:
                dto = ReservationDTO.from_payload(_merge_snapshot({"id": object_id}, raw))
                invoice_payload = client.get(f"/reservation/{object_id}/invoice", cancel=cancel)
                linked: list[tuple[InvoiceDTO, dict[str, Any]]] = []
                for invoice_link in _records(invoice_payload):
                    invoice_id = str(invoice_link.get("id") or invoice_link.get("invoice_id") or "").strip()
                    if not invoice_id:
                        continue
                    invoice_detail_payload = client.get(f"/invoice/{invoice_id}", cancel=cancel)
                    merged = _merge_snapshot(invoice_link, _single_record(invoice_detail_payload))
                    linked.append((InvoiceDTO.from_payload(merged, currencies), invoice_detail_payload))
                with self.database.transaction() as conn:
                    self._store_snapshot(conn, "reservation-detail", object_id, endpoint, payload, correlation)
                    self._store_snapshot(
                        conn,
                        "reservation-invoices",
                        object_id,
                        f"/reservation/{object_id}/invoice",
                        invoice_payload,
                        correlation,
                    )
                    self._persist_reservation(conn, dto, report)
                    for invoice_dto, invoice_detail_payload in linked:
                        self._store_snapshot(
                            conn,
                            "invoice-detail",
                            invoice_dto.external_id,
                            f"/invoice/{invoice_dto.external_id}",
                            invoice_detail_payload,
                            correlation,
                        )
                        self._persist_invoice(conn, invoice_dto, report)
                        now = utc_now()
                        conn.execute(
                            "INSERT INTO reservation_invoice_link(reservation_id,invoice_id,first_seen_utc,last_seen_utc) "
                            "VALUES(?,?,?,?) ON CONFLICT(reservation_id,invoice_id) DO UPDATE SET "
                            "last_seen_utc=excluded.last_seen_utc",
                            (object_id, invoice_dto.external_id, now, now),
                        )
                        if (dto.source_name or "").casefold() == "booking.com":
                            conn.execute("UPDATE invoice SET included=1 WHERE external_id=?", (invoice_dto.external_id,))
        elif normalized_type == "BILL":
            endpoint = f"/bill/{object_id}"
            payload = client.get(endpoint, cancel=cancel)
            raw = _single_record(payload)
            with self.database.transaction() as conn:
                self._store_snapshot(conn, "bill-detail", object_id, endpoint, payload, correlation)
                existing = conn.execute(
                    "SELECT reservation_id FROM bill WHERE external_id=?", (object_id,)
                ).fetchone()
                if raw:
                    merged = _merge_snapshot({"id": object_id}, raw)
                    reservation_id = str(
                        merged.get("reservation_id")
                        or merged.get("reservation_uuid")
                        or (existing["reservation_id"] if existing else "")
                        or ""
                    ).strip()
                    if not reservation_id:
                        raise BetterHotelDataError(
                            "Detail účtu neobsahuje vazbu na rezervaci a lokální vazba neexistuje."
                        )
                    self._persist_bill(conn, reservation_id, merged, currencies, report)
                elif existing is None:
                    raise BetterHotelDataError("Better Hotel nevrátil detail požadovaného účtu.")
                else:
                    report.diagnostics.append(
                        "Detail účtu obsahoval pouze metadata; uložený objekt zůstal beze změny."
                    )
                    report.unchanged["bill"] += 1
        else:
            endpoint = f"/bill-item/{object_id}"
            payload = client.get(endpoint, cancel=cancel)
            raw = _single_record(payload)
            with self.database.transaction() as conn:
                self._store_snapshot(conn, "bill-item-detail", object_id, endpoint, payload, correlation)
                existing = conn.execute(
                    "SELECT bill_id FROM bill_item WHERE external_id=?", (object_id,)
                ).fetchone()
                if raw:
                    merged = _merge_snapshot({"id": object_id}, raw)
                    bill_id = str(
                        merged.get("bill_id")
                        or merged.get("bill_uuid")
                        or (existing["bill_id"] if existing else "")
                        or ""
                    ).strip()
                    if not bill_id:
                        raise BetterHotelDataError(
                            "Detail položky účtu neobsahuje vazbu na účet a lokální vazba neexistuje."
                        )
                    self._persist_bill_item(conn, bill_id, merged, currencies, report)
                elif existing is None:
                    raise BetterHotelDataError("Better Hotel nevrátil detail požadované položky účtu.")
                else:
                    report.diagnostics.append(
                        "Detail položky účtu obsahoval pouze metadata; uložený objekt zůstal beze změny."
                    )
                    report.unchanged["bill_item"] += 1
        self._cancel_point(cancel)
        report.state = "SUCCEEDED"
        if progress:
            progress(1, 1, "Aktuální stav byl uložen")
        return report

    def sync_modified(
        self,
        client: BetterHotelClient,
        *,
        overlap_hours: int = 48,
        progress: ProgressCallback | None = None,
        cancel: CancelCallback | None = None,
    ) -> SyncReport:
        checkpoint = self.database.scalar("SELECT checkpoint_utc FROM api_checkpoint WHERE resource='invoice'")
        if checkpoint is None:
            return self.sync(
                client,
                first_day=date.today() - timedelta(days=7),
                overlap_hours=overlap_hours,
                progress=progress,
                cancel=cancel,
            )
        parsed = datetime.fromisoformat(str(checkpoint).replace("Z", "+00:00"))
        modified = parsed - timedelta(hours=overlap_hours)
        return self.sync(
            client,
            first_day=modified.date(),
            overlap_hours=overlap_hours,
            progress=progress,
            cancel=cancel,
            modified_since=modified.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        )

    def _sync_currencies(
        self,
        client: BetterHotelClient,
        report: SyncReport,
        cancel: CancelCallback | None,
        correlation_id: str,
    ) -> dict[str, str]:
        mapping: dict[str, str] = {"CZK": "CZK", "EUR": "EUR"}
        payload = client.get("/currency", cancel=cancel)
        records = _records(payload)
        with self.database.transaction() as conn:
            self._store_snapshot(conn, "currency-list", "all", "/currency", payload, correlation_id)
            for raw in records:
                external_id = str(raw.get("id") or raw.get("code") or "").strip()
                iso = str(raw.get("iso_code") or raw.get("code") or raw.get("name") or "").upper().strip()
                if iso not in {"CZK", "EUR"} or not external_id:
                    report.diagnostics.append("Číselník měn obsahoval neznámý nebo neúplný záznam.")
                    continue
                mapping[external_id] = iso
                digest = content_hash(raw)
                existing = conn.execute("SELECT content_hash FROM currency WHERE external_id=?", (external_id,)).fetchone()
                now = utc_now()
                if existing is None:
                    conn.execute(
                        "INSERT INTO currency(external_id,iso_code,raw_json,content_hash,updated_at_utc) VALUES(?,?,?,?,?)",
                        (external_id, iso, canonical_json(raw), digest, now),
                    )
                    report.inserted["currency"] += 1
                elif existing["content_hash"] != digest:
                    conn.execute(
                        "UPDATE currency SET iso_code=?,raw_json=?,content_hash=?,updated_at_utc=? WHERE external_id=?",
                        (iso, canonical_json(raw), digest, now, external_id),
                    )
                    report.updated["currency"] += 1
                else:
                    report.unchanged["currency"] += 1
        return mapping

    def _sync_invoices_block(
        self,
        client: BetterHotelClient,
        currencies: dict[str, str],
        start: date,
        end: date,
        report: SyncReport,
        cancel: CancelCallback | None,
        headers: dict[str, str] | None,
        progress: ProgressCallback | None,
    ) -> None:
        # The invoice collection endpoint expects its date range in the nested
        # `filter[...]` query namespace.  Reservation and financial-stats
        # endpoints still use the flat form, so this must stay local to invoices.
        params = {
            "filter[date_from]": start.isoformat(),
            "filter[date_to]": end.isoformat(),
        }
        total_items = 1
        for item_index, (list_raw, total_items) in enumerate(
            _iter_items_with_total(client, "/invoice", params=params, headers=headers, cancel=cancel),
            start=1,
        ):
            if progress and item_index == 1:
                progress(0, total_items, f"Doklady 0/{total_items} ({start:%d.%m.%Y}–{end:%d.%Y})")
            self._cancel_point(cancel)
            external_id = str(list_raw.get("id") or "").strip()
            if not external_id:
                report.diagnostics.append("Seznam faktur obsahoval záznam bez id.")
                continue
            # The collection response already contains all fields needed for the
            # document overview. Fetching a detail for every invoice turns a
            # 7,000-document sync into hours of rate-limited HTTP traffic. Use
            # the detail endpoint only when the collection record is incomplete.
            detail_payload: dict[str, Any] | None = None
            merged = dict(list_raw)
            try:
                dto = InvoiceDTO.from_payload(merged, currencies)
            except BetterHotelDataError as exc:
                detail_payload = client.get(f"/invoice/{external_id}", headers=headers, cancel=cancel)
                detail_raw = _single_record(detail_payload)
                merged = _merge_snapshot(list_raw, detail_raw)
                try:
                    dto = InvoiceDTO.from_payload(merged, currencies)
                except BetterHotelDataError as detail_exc:
                    report.diagnostics.append(str(detail_exc))
                    with self.database.transaction() as conn:
                        self._store_snapshot(conn, "invoice-invalid", external_id, f"/invoice/{external_id}", detail_payload, report.correlation_id)
                    if progress:
                        progress(item_index, total_items, f"Doklady {item_index}/{total_items} ({start:%d.%m.%Y}–{end:%d.%m.%Y})")
                    continue
            with self.database.transaction() as conn:
                self._store_snapshot(conn, "invoice-list", dto.external_id, "/invoice", list_raw, report.correlation_id)
                if detail_payload is not None:
                    self._store_snapshot(conn, "invoice-detail", dto.external_id, f"/invoice/{dto.external_id}", detail_payload, report.correlation_id)
                self._persist_invoice(conn, dto, report)
                self._persist_invoice_items(conn, dto, _embedded_items(merged, ("invoice_item", "invoice_items", "items")), currencies, report)
            if progress:
                progress(item_index, total_items, f"Doklady {item_index}/{total_items} ({start:%d.%m.%Y}–{end:%d.%m.%Y})")
        self._cancel_point(cancel)

    def _sync_reservations_block(
        self,
        client: BetterHotelClient,
        currencies: dict[str, str],
        start: date,
        end: date,
        report: SyncReport,
        cancel: CancelCallback | None,
        headers: dict[str, str] | None,
        progress: ProgressCallback | None,
        include_extended_reservation_details: bool = True,
    ) -> None:
        params: dict[str, Any] = {
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "expand[]": ["reservation_source", "reservation_note"],
        }
        total_items = 1
        prepared: list[dict[str, Any]] = []
        invalid_snapshots: list[tuple[str, dict[str, Any]]] = []
        for item_index, (list_raw, total_items) in enumerate(
            _iter_items_with_total(client, "/reservation", params=params, headers=headers, cancel=cancel),
            start=1,
        ):
            if progress and item_index == 1:
                progress(0, total_items, f"Rezervace 0/{total_items} ({start:%d.%m.%Y}–{end:%d.%m.%Y})")
            self._cancel_point(cancel)
            reservation_id = str(list_raw.get("id") or list_raw.get("uuid") or "").strip()
            if not reservation_id:
                report.diagnostics.append("Seznam rezervací obsahoval záznam bez UUID.")
                continue
            detail_payload = client.get(
                f"/reservation/{reservation_id}",
                params={"expand[]": ["reservation_source", "reservation_note"]},
                headers=headers,
                cancel=cancel,
            )
            detail_raw = _single_record(detail_payload)
            merged = _merge_snapshot(list_raw, detail_raw)
            try:
                dto = ReservationDTO.from_payload(merged)
            except BetterHotelDataError as exc:
                report.diagnostics.append(str(exc))
                invalid_snapshots.append((reservation_id, detail_payload))
                if progress:
                    progress(item_index, max(1, total_items), f"Rezervace {item_index}/{total_items} ({start:%d.%m.%Y}–{end:%d.%m.%Y})")
                continue

            invoice_payload = client.get(f"/reservation/{reservation_id}/invoice", headers=headers, cancel=cancel)
            invoice_details: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for link in _records(invoice_payload):
                invoice_id = str(link.get("id") or link.get("invoice_id") or "").strip()
                if not invoice_id:
                    continue
                linked_payload = client.get(f"/invoice/{invoice_id}", headers=headers, cancel=cancel)
                invoice_details.append((_merge_snapshot(link, _single_record(linked_payload)), linked_payload))

            bills: list[tuple[dict[str, Any], dict[str, Any], list[tuple[dict[str, Any], dict[str, Any]]]]] = []
            bill_payload: dict[str, Any] = {"data": []}
            deposit_payload: dict[str, Any] = {"data": []}
            if include_extended_reservation_details:
                bill_payload = client.get(f"/reservation/{reservation_id}/bill", headers=headers, cancel=cancel)
                for bill_link in _records(bill_payload):
                    bill_id = str(bill_link.get("id") or bill_link.get("bill_id") or "").strip()
                    if not bill_id:
                        continue
                    bill_detail_payload = client.get(f"/bill/{bill_id}", headers=headers, cancel=cancel)
                    bill_detail = _merge_snapshot(bill_link, _single_record(bill_detail_payload))
                    item_list_payload = client.get(f"/bill/{bill_id}/bill-item", headers=headers, cancel=cancel)
                    bill_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
                    for item_link in _records(item_list_payload):
                        item_id = str(item_link.get("id") or item_link.get("bill_item_id") or "").strip()
                        if not item_id:
                            continue
                        item_detail_payload = client.get(f"/bill-item/{item_id}", headers=headers, cancel=cancel)
                        bill_items.append((_merge_snapshot(item_link, _single_record(item_detail_payload)), item_detail_payload))
                    bills.append((bill_detail, bill_detail_payload, bill_items))
                deposit_payload = client.get(f"/reservation/{reservation_id}/security-deposit", headers=headers, cancel=cancel)
            fetched_bill_id = str(bills[0][0].get("id") or "").strip() if bills else None
            if fetched_bill_id and not dto.bill_id:
                merged = dict(merged)
                merged["bill_id"] = fetched_bill_id
                dto = ReservationDTO.from_payload(merged)
            prepared.append(
                {
                    "list_raw": list_raw,
                    "reservation_id": reservation_id,
                    "detail_payload": detail_payload,
                    "dto": dto,
                    "invoice_payload": invoice_payload,
                    "invoice_details": invoice_details,
                    "bill_payload": bill_payload,
                    "bills": bills,
                    "deposit_payload": deposit_payload,
                    "deposits": _records(deposit_payload),
                }
            )
            if progress:
                progress(item_index, max(1, total_items), f"Rezervace {item_index}/{total_items} ({start:%d.%m.%Y}–{end:%d.%m.%Y})")

        self._cancel_point(cancel)
        with self.database.transaction() as conn:
            for reservation_id, payload in invalid_snapshots:
                self._store_snapshot(conn, "reservation-invalid", reservation_id, f"/reservation/{reservation_id}", payload, report.correlation_id)
            for item in prepared:
                reservation_id = item["reservation_id"]
                dto = item["dto"]
                self._store_snapshot(conn, "reservation-list", reservation_id, "/reservation", item["list_raw"], report.correlation_id)
                self._store_snapshot(conn, "reservation-detail", reservation_id, f"/reservation/{reservation_id}", item["detail_payload"], report.correlation_id)
                self._store_snapshot(conn, "reservation-invoices", reservation_id, f"/reservation/{reservation_id}/invoice", item["invoice_payload"], report.correlation_id)
                self._store_snapshot(conn, "reservation-bills", reservation_id, f"/reservation/{reservation_id}/bill", item["bill_payload"], report.correlation_id)
                self._store_snapshot(conn, "security-deposit-list", reservation_id, f"/reservation/{reservation_id}/security-deposit", item["deposit_payload"], report.correlation_id)
                self._persist_reservation(conn, dto, report)
                for linked_raw, linked_payload in item["invoice_details"]:
                    invoice_id = str(linked_raw.get("id") or "").strip()
                    try:
                        linked_dto = InvoiceDTO.from_payload(linked_raw, currencies)
                    except BetterHotelDataError as exc:
                        report.diagnostics.append(str(exc))
                        continue
                    self._store_snapshot(conn, "invoice-detail", invoice_id, f"/invoice/{invoice_id}", linked_payload, report.correlation_id)
                    self._persist_invoice(conn, linked_dto, report)
                    self._persist_invoice_items(conn, linked_dto, _embedded_items(linked_raw, ("invoice_item", "invoice_items", "items")), currencies, report)
                    now = utc_now()
                    conn.execute(
                        "INSERT INTO reservation_invoice_link(reservation_id,invoice_id,first_seen_utc,last_seen_utc) VALUES(?,?,?,?) ON CONFLICT(reservation_id,invoice_id) DO UPDATE SET last_seen_utc=excluded.last_seen_utc",
                        (reservation_id, invoice_id, now, now),
                    )
                    if (dto.source_name or "").casefold() == "booking.com":
                        conn.execute("UPDATE invoice SET included=1 WHERE external_id=?", (invoice_id,))
                for bill_raw, bill_detail_payload, bill_items in item["bills"]:
                    self._persist_bill(conn, reservation_id, bill_raw, currencies, report)
                    bill_id = str(bill_raw.get("id") or "").strip()
                    self._store_snapshot(conn, "bill-detail", bill_id, f"/bill/{bill_id}", bill_detail_payload, report.correlation_id)
                    for bill_item_raw, item_payload in bill_items:
                        self._persist_bill_item(conn, bill_id, bill_item_raw, currencies, report)
                        item_id = str(bill_item_raw.get("id") or "").strip()
                        self._store_snapshot(conn, "bill-item-detail", item_id, f"/bill-item/{item_id}", item_payload, report.correlation_id)
                self._persist_security_deposits(conn, reservation_id, item["deposits"], currencies, report)

    def _persist_invoice(self, conn: Any, dto: InvoiceDTO, report: SyncReport) -> None:
        existing = conn.execute(
            "SELECT content_hash,total_minor,currency_code,archived_at_utc,print_format FROM invoice WHERE external_id=?",
            (dto.external_id,),
        ).fetchone()
        now = utc_now()
        if existing is None:
            conn.execute(
                "INSERT INTO invoice(external_id,document_uuid,code,document_date_utc,due_date_utc,vat_date_utc,paid_at_utc,archived_at_utc,total_minor,subtotal_minor,deposit_minor,currency_code,pay_method,print_format,exchange_rate,vat_exchange_rate,included,status,raw_json,content_hash,first_seen_utc,last_seen_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,'UNMATCHED',?,?,?,?,1)",
                (
                    dto.external_id,
                    dto.document_uuid,
                    dto.code,
                    dto.document_date_utc,
                    dto.due_date_utc,
                    dto.vat_date_utc,
                    dto.paid_at_utc,
                    dto.archived_at_utc,
                    dto.total_minor,
                    dto.subtotal_minor,
                    dto.deposit_minor,
                    dto.currency_code,
                    dto.pay_method,
                    dto.print_format,
                    dto.exchange_rate,
                    dto.vat_exchange_rate,
                    dto.raw_json,
                    dto.content_hash,
                    now,
                    now,
                ),
            )
            report.inserted["invoice"] += 1
            return
        if existing["content_hash"] == dto.content_hash:
            conn.execute("UPDATE invoice SET last_seen_utc=? WHERE external_id=?", (now, dto.external_id))
            report.unchanged["invoice"] += 1
            return
        changed_fields = [
            field
            for field, old, new in (
                ("total_minor", existing["total_minor"], dto.total_minor),
                ("currency_code", existing["currency_code"], dto.currency_code),
                ("archived_at_utc", existing["archived_at_utc"], dto.archived_at_utc),
                ("print_format", existing["print_format"], dto.print_format),
            )
            if old != new
        ]
        conn.execute(
            "UPDATE invoice SET document_uuid=?,code=?,document_date_utc=?,due_date_utc=?,vat_date_utc=?,paid_at_utc=?,archived_at_utc=?,total_minor=?,subtotal_minor=?,deposit_minor=?,currency_code=?,pay_method=?,print_format=?,exchange_rate=?,vat_exchange_rate=?,raw_json=?,content_hash=?,last_seen_utc=?,row_version=row_version+1 WHERE external_id=?",
            (
                dto.document_uuid,
                dto.code,
                dto.document_date_utc,
                dto.due_date_utc,
                dto.vat_date_utc,
                dto.paid_at_utc,
                dto.archived_at_utc,
                dto.total_minor,
                dto.subtotal_minor,
                dto.deposit_minor,
                dto.currency_code,
                dto.pay_method,
                dto.print_format,
                dto.exchange_rate,
                dto.vat_exchange_rate,
                dto.raw_json,
                dto.content_hash,
                now,
                dto.external_id,
            ),
        )
        if changed_fields:
            self._revision_alert(conn, "INVOICE", dto.external_id, existing["content_hash"], dto.content_hash, changed_fields)
        report.updated["invoice"] += 1

    def _persist_invoice_items(self, conn: Any, invoice: InvoiceDTO, records: Iterable[dict[str, Any]], currencies: dict[str, str], report: SyncReport) -> None:
        for raw in records:
            external_id = str(raw.get("id") or raw.get("uuid") or "").strip()
            if not external_id:
                report.diagnostics.append(f"Položka faktury {invoice.code} nemá stabilní id.")
                continue
            try:
                code = currency_code(raw.get("currency", invoice.currency_code), {**currencies, invoice.currency_code: invoice.currency_code})
                signed = amount_minor(raw.get("signed_amount", raw.get("amount", raw.get("total", 0))), code)
            except BetterHotelDataError as exc:
                report.diagnostics.append(str(exc))
                continue
            digest = content_hash(raw)
            existing = conn.execute("SELECT content_hash FROM invoice_item WHERE external_id=?", (external_id,)).fetchone()
            values = (
                invoice.external_id,
                str(raw.get("bill_item_id") or raw.get("bill_item") or "").strip() or None,
                signed,
                code,
                str(raw.get("vat_type") or "").strip() or None,
                _date_value(raw.get("service_from") or raw.get("date_from")),
                _date_value(raw.get("service_to") or raw.get("date_to")),
                canonical_json(raw),
                digest,
                external_id,
            )
            if existing is None:
                conn.execute(
                    "INSERT INTO invoice_item(invoice_id,bill_item_id,signed_amount_minor,currency_code,vat_type,service_from,service_to,raw_json,content_hash,external_id,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                    values,
                )
                report.inserted["invoice_item"] += 1
            elif existing["content_hash"] != digest:
                conn.execute(
                    "UPDATE invoice_item SET invoice_id=?,bill_item_id=?,signed_amount_minor=?,currency_code=?,vat_type=?,service_from=?,service_to=?,raw_json=?,content_hash=?,row_version=row_version+1 WHERE external_id=?",
                    values,
                )
                report.updated["invoice_item"] += 1
            else:
                report.unchanged["invoice_item"] += 1

    def _persist_reservation(self, conn: Any, dto: ReservationDTO, report: SyncReport) -> None:
        existing = conn.execute("SELECT content_hash FROM reservation WHERE uuid=?", (dto.uuid,)).fetchone()
        now = utc_now()
        extraction = self.parser.extract(dto.uuid, dto.channels)
        booking_ref = extraction.confirmed_candidate
        reference_status = extraction.status
        if existing is None:
            conn.execute(
                "INSERT INTO reservation(uuid,internal_code,source_id,source_name,arrival,departure,bill_id,booking_reference,reference_status,raw_json,content_hash,first_seen_utc,last_seen_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (
                    dto.uuid,
                    dto.internal_code,
                    dto.source_id,
                    dto.source_name,
                    dto.arrival,
                    dto.departure,
                    dto.bill_id,
                    booking_ref,
                    reference_status,
                    dto.raw_json,
                    dto.content_hash,
                    now,
                    now,
                ),
            )
            report.inserted["reservation"] += 1
        elif existing["content_hash"] == dto.content_hash:
            conn.execute("UPDATE reservation SET last_seen_utc=? WHERE uuid=?", (now, dto.uuid))
            report.unchanged["reservation"] += 1
        else:
            conn.execute(
                "UPDATE reservation SET internal_code=?,source_id=?,source_name=?,arrival=?,departure=?,bill_id=?,booking_reference=?,reference_status=?,raw_json=?,content_hash=?,last_seen_utc=?,row_version=row_version+1 WHERE uuid=?",
                (
                    dto.internal_code,
                    dto.source_id,
                    dto.source_name,
                    dto.arrival,
                    dto.departure,
                    dto.bill_id,
                    booking_ref,
                    reference_status,
                    dto.raw_json,
                    dto.content_hash,
                    now,
                    dto.uuid,
                ),
            )
            report.updated["reservation"] += 1
        self._store_extractions(conn, dto.uuid, dto.channels, extraction)
        self._upsert_reservation_group(conn, dto.uuid, dto.internal_code, booking_ref)

    def _persist_bill(self, conn: Any, reservation_id: str, raw: dict[str, Any], currencies: dict[str, str], report: SyncReport) -> None:
        bill_id = str(raw.get("id") or raw.get("uuid") or "").strip()
        if not bill_id:
            return
        try:
            code = currency_code(raw.get("currency", "CZK"), currencies)
            total = amount_minor(raw.get("total", 0), code)
            balance = amount_minor(raw.get("balance", raw.get("saldo", 0)), code)
        except BetterHotelDataError as exc:
            report.diagnostics.append(str(exc))
            return
        digest = content_hash(raw)
        existing = conn.execute("SELECT content_hash FROM bill WHERE external_id=?", (bill_id,)).fetchone()
        values = (
            reservation_id,
            total,
            balance,
            code,
            _bool_int(raw.get("is_closed", raw.get("closed"))),
            _bool_int(raw.get("is_locked", raw.get("locked"))),
            canonical_json(raw),
            digest,
            bill_id,
        )
        if existing is None:
            conn.execute(
                "INSERT INTO bill(reservation_id,total_minor,balance_minor,currency_code,is_closed,is_locked,raw_json,content_hash,external_id,row_version) VALUES(?,?,?,?,?,?,?,?,?,1)",
                values,
            )
            report.inserted["bill"] += 1
        elif existing["content_hash"] != digest:
            conn.execute(
                "UPDATE bill SET reservation_id=?,total_minor=?,balance_minor=?,currency_code=?,is_closed=?,is_locked=?,raw_json=?,content_hash=?,row_version=row_version+1 WHERE external_id=?",
                values,
            )
            report.updated["bill"] += 1
        else:
            report.unchanged["bill"] += 1
        conn.execute("UPDATE reservation SET bill_id=? WHERE uuid=?", (bill_id, reservation_id))

    def _persist_bill_item(self, conn: Any, bill_id: str, raw: dict[str, Any], currencies: dict[str, str], report: SyncReport) -> None:
        item_id = str(raw.get("id") or raw.get("uuid") or "").strip()
        if not item_id:
            return
        try:
            code = currency_code(raw.get("currency", "CZK"), currencies)
            amount = amount_minor(raw.get("amount", raw.get("total", 0)), code)
        except BetterHotelDataError as exc:
            report.diagnostics.append(str(exc))
            return
        digest = content_hash(raw)
        existing = conn.execute("SELECT content_hash FROM bill_item WHERE external_id=?", (item_id,)).fetchone()
        values = (bill_id, amount, code, canonical_json(raw), digest, item_id)
        if existing is None:
            conn.execute(
                "INSERT INTO bill_item(bill_id,amount_minor,currency_code,raw_json,content_hash,external_id,row_version) VALUES(?,?,?,?,?,?,1)",
                values,
            )
            report.inserted["bill_item"] += 1
        elif existing["content_hash"] != digest:
            conn.execute(
                "UPDATE bill_item SET bill_id=?,amount_minor=?,currency_code=?,raw_json=?,content_hash=?,row_version=row_version+1 WHERE external_id=?",
                values,
            )
            report.updated["bill_item"] += 1
        else:
            report.unchanged["bill_item"] += 1

    def _persist_security_deposits(self, conn: Any, reservation_id: str, deposits: Iterable[dict[str, Any]], currencies: dict[str, str], report: SyncReport) -> None:
        for raw in deposits:
            deposit_id = str(raw.get("id") or raw.get("uuid") or "").strip()
            if not deposit_id:
                continue
            try:
                code = currency_code(raw.get("currency", "CZK"), currencies)
                amount = amount_minor(raw.get("amount", raw.get("total", 0)), code)
            except BetterHotelDataError as exc:
                report.diagnostics.append(str(exc))
                continue
            digest = content_hash(raw)
            existing = conn.execute("SELECT content_hash FROM security_deposit WHERE external_id=?", (deposit_id,)).fetchone()
            now = utc_now()
            values = (
                reservation_id,
                amount,
                code,
                str(raw.get("status") or "").strip() or None,
                canonical_json(raw),
                digest,
                now,
                deposit_id,
            )
            if existing is None:
                conn.execute(
                    "INSERT INTO security_deposit(reservation_id,amount_minor,currency_code,status,raw_json,content_hash,first_seen_utc,last_seen_utc,external_id,row_version) VALUES(?,?,?,?,?,?,?,?,?,1)",
                    (reservation_id, amount, code, values[3], values[4], digest, now, now, deposit_id),
                )
                report.inserted["security_deposit"] += 1
            elif existing["content_hash"] != digest:
                conn.execute(
                    "UPDATE security_deposit SET reservation_id=?,amount_minor=?,currency_code=?,status=?,raw_json=?,content_hash=?,last_seen_utc=?,row_version=row_version+1 WHERE external_id=?",
                    values,
                )
                report.updated["security_deposit"] += 1
            else:
                conn.execute("UPDATE security_deposit SET last_seen_utc=? WHERE external_id=?", (now, deposit_id))
                report.unchanged["security_deposit"] += 1

    def _sync_financial_stats(
        self,
        client: BetterHotelClient,
        first_day: date,
        last_day: date,
        report: SyncReport,
        cancel: CancelCallback | None,
        correlation_id: str,
    ) -> None:
        payload = client.get(
            "/financial-stats",
            params={"date_from": first_day.isoformat(), "date_to": last_day.isoformat()},
            cancel=cancel,
        )
        digest = content_hash(payload)
        with self.database.transaction() as conn:
            self._store_snapshot(conn, "financial-stats", f"{first_day}:{last_day}", "/financial-stats", payload, correlation_id)
            existing = conn.execute("SELECT id FROM financial_stats_snapshot WHERE content_hash=?", (digest,)).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO financial_stats_snapshot(id,range_start,range_end,raw_json,content_hash,fetched_at_utc,correlation_id) VALUES(?,?,?,?,?,?,?)",
                    (uuid4().hex, first_day.isoformat(), last_day.isoformat(), canonical_json(payload), digest, utc_now(), correlation_id),
                )
                report.inserted["financial_stats"] += 1
            else:
                report.unchanged["financial_stats"] += 1

    def _store_extractions(self, conn: Any, reservation_id: str, channels: tuple[str, ...], extraction: Any) -> None:
        now = utc_now()
        for channel in channels:
            snapshot_hash = hashlib.sha256(channel.encode("utf-8")).hexdigest()
            snapshot_id = hashlib.sha256(f"{reservation_id}|{snapshot_hash}".encode()).hexdigest()
            preview = self.parser.redacted_preview(channel)
            conn.execute(
                "INSERT INTO reservation_note_snapshot(id,reservation_id,raw_channel,redacted_preview,content_hash,fetched_at_utc) VALUES(?,?,?,?,?,?) ON CONFLICT(reservation_id,content_hash) DO UPDATE SET fetched_at_utc=excluded.fetched_at_utc",
                (snapshot_id, reservation_id, channel, preview, snapshot_hash, now),
            )
        for candidate in extraction.candidates:
            extraction_id = hashlib.sha256(
                f"{candidate.raw_snapshot_hash}|{candidate.candidate}|{candidate.label}|{candidate.start_offset}|{self.parser.version}".encode()
            ).hexdigest()
            snapshot_id = hashlib.sha256(f"{reservation_id}|{candidate.raw_snapshot_hash}".encode()).hexdigest()
            conn.execute(
                "INSERT OR IGNORE INTO booking_reference_extraction(id,snapshot_id,reservation_id,candidate,label,start_offset,end_offset,status,parser_version,extracted_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    extraction_id,
                    snapshot_id,
                    reservation_id,
                    candidate.candidate,
                    candidate.label,
                    candidate.start_offset,
                    candidate.end_offset,
                    extraction.status,
                    self.parser.version,
                    now,
                ),
            )

    @staticmethod
    def _upsert_reservation_group(conn: Any, reservation_id: str, internal_code: str, booking_ref: str | None) -> None:
        group_id = hashlib.sha256(f"{internal_code}|{booking_ref or ''}".encode()).hexdigest()
        conn.execute(
            "INSERT INTO reservation_group(id,internal_code,booking_reference,row_version) VALUES(?,?,?,1) ON CONFLICT(internal_code,booking_reference) DO NOTHING",
            (group_id, internal_code, booking_ref),
        )
        row = conn.execute(
            "SELECT id FROM reservation_group WHERE internal_code=? AND booking_reference IS ?", (internal_code, booking_ref)
        ).fetchone()
        if row is not None:
            conn.execute(
                "INSERT OR IGNORE INTO reservation_group_member(group_id,reservation_id) VALUES(?,?)",
                (row["id"], reservation_id),
            )

    @staticmethod
    def _revision_alert(
        conn: Any, entity_type: str, entity_id: str, old_hash: str, new_hash: str, changed_fields: list[str]
    ) -> None:
        affected = [
            row[0]
            for row in conn.execute(
                "SELECT group_id FROM match_group_document WHERE invoice_id=? AND active=1"
                if entity_type == "INVOICE"
                else "SELECT group_id FROM match_group_source WHERE entity_type=? AND entity_id=? AND active=1",
                (entity_id,) if entity_type == "INVOICE" else (entity_type, entity_id),
            ).fetchall()
        ]
        if not affected:
            return
        now = utc_now()
        conn.execute(
            "INSERT INTO source_revision_alert(id,object_ref,previous_hash,current_hash,changed_fields_json,affected_group_ids_json,state,detected_at_utc) VALUES(?,?,?,?,?,?,?,?)",
            (uuid4().hex, f"{entity_type}:{entity_id}", old_hash, new_hash, canonical_json(changed_fields), canonical_json(affected), "OPEN", now),
        )
        placeholders = ",".join("?" for _ in affected)
        conn.execute(
            f"UPDATE match_group SET status='REVIEW_REQUIRED',review_required_reason='Zdrojová data se změnila',row_version=row_version+1,updated_at_utc=? WHERE id IN ({placeholders})",
            (now, *affected),
        )

    @staticmethod
    def _store_snapshot(conn: Any, resource_type: str, external_id: str, endpoint: str, payload: Any, correlation_id: str) -> None:
        digest = content_hash(payload)
        conn.execute(
            "INSERT OR IGNORE INTO api_raw_snapshot(id,resource_type,external_id,endpoint,raw_json,content_hash,fetched_at_utc,correlation_id) VALUES(?,?,?,?,?,?,?,?)",
            (uuid4().hex, resource_type, external_id, endpoint, canonical_json(payload), digest, utc_now(), correlation_id),
        )

    def _checkpoint(self, resource: str, through: date, overlap_hours: int) -> None:
        checkpoint = datetime.combine(through + timedelta(days=1), datetime.min.time(), tzinfo=UTC).isoformat().replace("+00:00", "Z")
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO api_checkpoint(resource,checkpoint_utc,overlap_seconds,updated_at_utc) VALUES(?,?,?,?) ON CONFLICT(resource) DO UPDATE SET checkpoint_utc=excluded.checkpoint_utc,overlap_seconds=excluded.overlap_seconds,updated_at_utc=excluded.updated_at_utc",
                (resource, checkpoint, overlap_hours * 3600, utc_now()),
            )

    def _heartbeat(self, run_id: str) -> None:
        with self.database.transaction() as conn:
            conn.execute("UPDATE api_sync_run SET heartbeat_at_utc=? WHERE id=?", (utc_now(), run_id))

    def _finish_run(self, report: SyncReport, error: str | None) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE api_sync_run SET state=?,counts_json=?,error_json=?,heartbeat_at_utc=?,finished_at_utc=? WHERE id=?",
                (
                    report.state,
                    canonical_json(
                        {
                            "inserted": report.inserted,
                            "updated": report.updated,
                            "unchanged": report.unchanged,
                            "diagnostics": len(report.diagnostics),
                        }
                    ),
                    None if error is None else canonical_json({"message": error}),
                    utc_now(),
                    utc_now(),
                    report.run_id,
                ),
            )

    @staticmethod
    def _cancel_point(cancel: CancelCallback | None) -> None:
        if cancel is not None and cancel():
            raise BetterHotelCancelled("Synchronizace byla bezpečně zrušena.")


def _iter_items_with_total(
    client: BetterHotelClient,
    path: str,
    *,
    params: dict[str, Any],
    headers: dict[str, str] | None,
    cancel: CancelCallback | None,
) -> Iterable[tuple[dict[str, Any], int]]:
    """Stream collection items while retaining the API's real total count."""
    if not hasattr(client, "pages"):
        for item in client.iter_items(path, params=params, headers=headers, cancel=cancel):
            yield item, 1
        return
    for page in client.pages(path, params=params, headers=headers, cancel=cancel):
        total = max(1, page.total_count)
        for item in page.data:
            yield item, total


def _records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    value = payload.get("data", [])
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _single_record(payload: Any) -> dict[str, Any]:
    records = _records(payload)
    if records:
        return records[0]
    # Better Hotel returns some GET detail endpoints as a bare object while
    # collection endpoints use {"data": [...]}. Accept both shapes.
    if isinstance(payload, dict) and (payload.get("id") or payload.get("uuid")):
        return payload
    return {}


def _merge_snapshot(base: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    if not detail:
        return dict(base)
    merged = dict(base)
    merged.update(detail)
    return merged


def _embedded_items(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _bool_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(bool(value))
    return int(str(value).strip().casefold() in {"1", "true", "yes", "ano", "closed", "locked"})


def _date_value(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else text


def _date_blocks(start: date, end: date, block_days: int) -> list[tuple[date, date]]:
    if start > end:
        return []
    blocks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        block_end = min(end, cursor + timedelta(days=block_days - 1))
        blocks.append((cursor, block_end))
        cursor = block_end + timedelta(days=1)
    return blocks
