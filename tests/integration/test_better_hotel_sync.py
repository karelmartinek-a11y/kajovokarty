from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from kajovokarty.domain.reference_parser import ReservationReferenceParser
from kajovokarty.infrastructure.better_hotel.client import BetterHotelCancelled
from kajovokarty.infrastructure.better_hotel.sync import BetterHotelSyncService
from kajovokarty.infrastructure.persistence.database import Database


class FakeClient:
    def __init__(self, *, two_invoices: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, str] | None]] = []
        self.invoice_details = 0
        self.two_invoices = two_invoices

    def iter_items(self, path: str, **kwargs: Any):
        self.calls.append((path, dict(kwargs.get("params") or {}), kwargs.get("headers")))
        if path == "/invoice":
            items = [self._invoice("inv1", "FA1")]
            if self.two_invoices:
                items.append(self._invoice("inv2", "FA2"))
            yield from items
        elif path == "/reservation":
            yield {"id": "res1", "code": 120268038.0}
        else:
            return

    def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((path, dict(kwargs.get("params") or {}), kwargs.get("headers")))
        if path == "/currency":
            return {"data": [{"id": 1, "iso_code": "EUR"}, {"id": 2, "iso_code": "CZK"}]}
        if path == "/invoice/inv1":
            self.invoice_details += 1
            return {"data": {**self._invoice("inv1", "FA1"), "invoice_items": [{"id": "ii1", "amount": "100.00", "currency": 1, "bill_item_id": "bi1"}]}}
        if path == "/invoice/inv2":
            self.invoice_details += 1
            return {"data": self._invoice("inv2", "FA2")}
        if path == "/reservation/res1":
            return {
                "data": {
                    "id": "res1",
                    "code": 120268038.0,
                    "arrival": "2026-07-30",
                    "departure": "2026-07-31",
                    "reservation_source": {"id": "booking", "name": "Booking.com"},
                    "reservation_note": [{"channel": "Original ID: 6689102875"}],
                }
            }
        if path == "/reservation/res1/invoice":
            return {"data": [{"id": "inv1"}]}
        if path == "/reservation/res1/bill":
            return {"data": [{"id": "bill1"}]}
        if path == "/bill/bill1":
            return {"data": {"id": "bill1", "total": "100.00", "balance": "0", "currency": 1, "is_closed": True, "is_locked": False}}
        if path == "/bill/bill1/bill-item":
            return {"data": [{"id": "bi1"}]}
        if path == "/bill-item/bi1":
            return {"data": {"id": "bi1", "amount": "100.00", "currency": 1}}
        if path == "/reservation/res1/security-deposit":
            return {"data": [{"id": "dep1", "amount": "20.00", "currency": 1, "status": "held"}]}
        if path == "/financial-stats":
            return {"data": {"diagnostic": True}}
        raise AssertionError(f"Neočekávaný endpoint {path}")

    @staticmethod
    def _invoice(identifier: str, code: str) -> dict[str, Any]:
        return {
            "id": identifier,
            "code": code,
            "date": "2026-07-31T10:00:00+00:00",
            "total": "100.00",
            "subtotal": "100.00",
            "deposit": "0",
            "currency": 1,
            "pay_method": 1,
            "print_format": 1,
        }


def test_sync_covers_details_links_bills_deposit_raw_snapshots_and_booking_scope(database: Database) -> None:
    client = FakeClient()
    progress: list[tuple[int, int, str]] = []
    report = BetterHotelSyncService(database, ReservationReferenceParser()).sync(
        client,
        first_day=date.today(),
        progress=lambda current, total, message: progress.append((current, total, message)),
    )

    assert report.state == "SUCCEEDED"
    assert database.scalar("SELECT COUNT(*) FROM invoice") == 1
    assert database.scalar("SELECT COUNT(*) FROM invoice_item") == 1
    assert database.scalar("SELECT COUNT(*) FROM reservation") == 1
    assert database.scalar("SELECT booking_reference FROM reservation WHERE uuid='res1'") == "6689102875"
    assert database.scalar("SELECT COUNT(*) FROM reservation_invoice_link") == 1
    assert database.scalar("SELECT included FROM invoice WHERE external_id='inv1'") == 1
    assert database.scalar("SELECT COUNT(*) FROM bill") == 1
    assert database.scalar("SELECT COUNT(*) FROM bill_item") == 1
    assert database.scalar("SELECT COUNT(*) FROM security_deposit") == 1
    assert database.scalar("SELECT COUNT(*) FROM financial_stats_snapshot") == 1
    assert database.scalar("SELECT COUNT(*) FROM api_raw_snapshot") >= 10
    assert database.scalar("SELECT state FROM api_sync_run") == "SUCCEEDED"
    assert database.scalar("SELECT checkpoint_utc FROM api_checkpoint WHERE resource='invoice'") is not None
    invoice_calls = [call for call in client.calls if call[0] == "/invoice"]
    assert invoice_calls[0][1] == {"filter[date_from]": date.today().isoformat(), "filter[date_to]": date.today().isoformat()}
    assert any(current == 1 and total == 1 and message.startswith("Doklady 1/1") for current, total, message in progress)
    assert any(current == 1 and total == 1 and message.startswith("Rezervace 1/1") for current, total, message in progress)


def test_modified_sync_sends_x_modified_and_preserves_existing_on_meta_only_details(database: Database) -> None:
    service = BetterHotelSyncService(database)
    initial = FakeClient()
    service.sync(initial, first_day=date.today())

    class MetaOnlyClient(FakeClient):
        def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
            if path.startswith("/invoice/") and path.count("/") == 2:
                self.calls.append((path, dict(kwargs.get("params") or {}), kwargs.get("headers")))
                return {"meta": {"ok": True}}
            return super().get(path, **kwargs)

    modified = MetaOnlyClient()
    report = service.sync_modified(modified)
    assert report.state == "SUCCEEDED"
    assert database.scalar("SELECT total_minor FROM invoice WHERE external_id='inv1'") == 10_000
    guarded_calls = [call for call in modified.calls if call[0] in {"/invoice", "/reservation", "/invoice/inv1", "/reservation/res1"}]
    assert guarded_calls
    assert all(call[2] and call[2].get("X-Modified") for call in guarded_calls)


def test_sync_accepts_bare_invoice_detail_payload(database: Database) -> None:
    class BareDetailClient(FakeClient):
        def iter_items(self, path: str, **kwargs: Any):
            if path == "/invoice":
                yield {"id": "inv1"}
                return
            yield from super().iter_items(path, **kwargs)

        def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
            if path == "/invoice/inv1":
                return {
                    **self._invoice("inv1", "FA1"),
                    "items": [{"id": "ii1", "amount": "100.00", "currency": 1}],
                }
            return super().get(path, **kwargs)

    report = BetterHotelSyncService(database).sync(BareDetailClient(), first_day=date.today())

    assert report.state == "SUCCEEDED"
    assert report.inserted["invoice"] == 1
    assert database.scalar("SELECT COUNT(*) FROM invoice") == 1


def test_cancel_during_invoice_fetch_keeps_completed_documents(database: Database) -> None:
    client = FakeClient(two_invoices=True)
    service = BetterHotelSyncService(database)

    def cancel() -> bool:
        return database.scalar("SELECT COUNT(*) FROM invoice") >= 1

    with pytest.raises(BetterHotelCancelled):
        service.sync(client, first_day=date.today(), cancel=cancel)
    assert database.scalar("SELECT COUNT(*) FROM invoice") == 1
    assert database.scalar("SELECT checkpoint_utc FROM api_checkpoint WHERE resource='invoice'") is None
    assert database.scalar("SELECT state FROM api_sync_run") == "CANCELLED"


def test_refresh_invoice_persists_change_through_revision_aware_path(database: Database) -> None:
    service = BetterHotelSyncService(database)
    service.sync(FakeClient(), first_day=date.today())

    class ChangedInvoiceClient(FakeClient):
        def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
            if path == "/invoice/inv1":
                raw = self._invoice("inv1", "FA1")
                raw["total"] = "125.50"
                return {"data": raw}
            return super().get(path, **kwargs)

    report = service.refresh_object(
        ChangedInvoiceClient(), object_type="INVOICE", object_id="inv1"
    )
    assert report.state == "SUCCEEDED"
    assert report.updated["invoice"] == 1
    assert database.scalar("SELECT total_minor FROM invoice WHERE external_id='inv1'") == 12_550
    assert database.scalar(
        "SELECT COUNT(*) FROM api_raw_snapshot WHERE resource_type='invoice-detail' AND external_id='inv1'"
    ) >= 2


def test_refresh_meta_only_does_not_erase_existing_object(database: Database) -> None:
    service = BetterHotelSyncService(database)
    service.sync(FakeClient(), first_day=date.today())

    class MetaOnly:
        def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
            assert path == "/invoice/inv1"
            return {"meta": {"ok": True}}

    report = service.refresh_object(MetaOnly(), object_type="INVOICE", object_id="inv1")
    assert report.unchanged["invoice"] == 1
    assert database.scalar("SELECT total_minor FROM invoice WHERE external_id='inv1'") == 10_000


def test_refresh_reservation_updates_core_and_linked_invoice(database: Database) -> None:
    service = BetterHotelSyncService(database)
    report = service.refresh_object(
        FakeClient(), object_type="RESERVATION", object_id="res1"
    )
    assert report.state == "SUCCEEDED"
    assert database.scalar("SELECT internal_code FROM reservation WHERE uuid='res1'") == "120268038"
    assert database.scalar("SELECT booking_reference FROM reservation WHERE uuid='res1'") == "6689102875"
    assert database.scalar("SELECT COUNT(*) FROM reservation_invoice_link") == 1
    assert database.scalar("SELECT included FROM invoice WHERE external_id='inv1'") == 1


def test_refresh_bill_and_bill_item_use_documented_get_endpoints(database: Database) -> None:
    service = BetterHotelSyncService(database)
    service.sync(FakeClient(), first_day=date.today())

    class ChangedBillClient(FakeClient):
        def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
            if path == "/bill/bill1":
                self.calls.append((path, dict(kwargs.get("params") or {}), kwargs.get("headers")))
                return {"data": {"id": "bill1", "total": "150.00", "balance": "50.00", "currency": 1}}
            if path == "/bill-item/bi1":
                self.calls.append((path, dict(kwargs.get("params") or {}), kwargs.get("headers")))
                return {"data": {"id": "bi1", "amount": "150.00", "currency": 1}}
            return super().get(path, **kwargs)

    client = ChangedBillClient()
    bill_report = service.refresh_object(client, object_type="BILL", object_id="bill1")
    item_report = service.refresh_object(client, object_type="BILL_ITEM", object_id="bi1")
    assert bill_report.updated["bill"] == 1
    assert item_report.updated["bill_item"] == 1
    assert database.scalar("SELECT balance_minor FROM bill WHERE external_id='bill1'") == 5_000
    assert database.scalar("SELECT amount_minor FROM bill_item WHERE external_id='bi1'") == 15_000
    paths = [call[0] for call in client.calls]
    assert "/bill/bill1" in paths
    assert "/bill-item/bi1" in paths
