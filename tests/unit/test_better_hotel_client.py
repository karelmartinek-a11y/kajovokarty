from __future__ import annotations

import httpx
import pytest

from kajovokarty.app.config import BETTER_HOTEL_BASE_URL
from kajovokarty.infrastructure.better_hotel import client as client_module
from kajovokarty.infrastructure.better_hotel.client import (
    BetterHotelAuthError,
    BetterHotelClient,
    BetterHotelError,
    CursorCycleError,
    Tokens,
)
from kajovokarty.infrastructure.better_hotel.dto import InvoiceDTO, ReservationDTO


def test_endpoint_headers_get_only_and_cursor_repeats_filters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["X-Access-Token"] == "access"
        assert request.headers["X-Client-Token"] == "client"
        params = dict(request.url.params.multi_items())
        assert params["count"] == "25"
        assert params["date_from"] == "2026-01-01"
        if "cursor" not in params:
            return httpx.Response(200, json={"data": [{"id": "a"}], "meta": {"total_count": 2, "cursor": "next", "has_more": True}})
        assert params["cursor"] == "next"
        return httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}], "meta": {"total_count": 2, "cursor": None, "has_more": False}})

    transport = httpx.MockTransport(handler)
    with BetterHotelClient(Tokens("access", "client"), transport=transport) as client:
        pages = list(client.pages("/invoice", params={"date_from": "2026-01-01"}))
        assert client.base_url == BETTER_HOTEL_BASE_URL
    assert [item["id"] for page in pages for item in page.data] == ["a", "b"]
    assert len(requests) == 2


def test_cursor_cycle_stops_safely() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "meta": {"total_count": 0, "cursor": "same", "has_more": True}})

    with BetterHotelClient(Tokens("a", "b"), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CursorCycleError):
            list(client.pages("/invoice"))


def test_429_respects_retry_and_auth_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(client_module, "_cooperative_sleep", lambda seconds, cancel: sleeps.append(seconds))
    with BetterHotelClient(Tokens("a", "b"), retries=1, transport=httpx.MockTransport(handler)) as client:
        assert client.get("/currency") == {"data": []}
    assert sleeps == [2.0]

    auth_calls = 0

    def auth_handler(_: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        auth_calls += 1
        return httpx.Response(401, json={"message": "secret must not be exposed"})

    with BetterHotelClient(Tokens("a", "b"), retries=5, transport=httpx.MockTransport(auth_handler)) as client:
        with pytest.raises(BetterHotelAuthError):
            client.get("/invoice")
    assert auth_calls == 1


def test_invoice_and_reservation_normalization() -> None:
    invoice = InvoiceDTO.from_payload(
        {
            "id": "inv-1",
            "document_uuid": None,
            "code": "FA20265875",
            "date": "2026-07-30T10:00:00+00:00",
            "paid": "2026-07-31T10:00:00.000100+00:00",
            "payed": "2026-07-31T10:00:00.000200+00:00",
            "currency": 1,
            "total": "100.00",
            "subtotal": "100.00",
            "deposit": "0",
            "pay_method": 1,
            "print_format": 3,
        },
        {"1": "EUR"},
    )
    assert invoice.total_minor == -10000
    assert invoice.paid_at_utc == "2026-07-31T10:00:00.000100Z"
    assert invoice.document_uuid is None

    reservation = ReservationDTO.from_payload(
        {
            "id": "reservation-1",
            "code": 120268038.0,
            "reservation_source": {"id": "booking", "name": "Booking.com"},
            "reservation_note": [{"channel": "Other"}, {"channel": "Original ID: 6689102875"}],
        }
    )
    assert reservation.internal_code == "120268038"
    assert reservation.channels == ("Other", "Original ID: 6689102875")


def test_error_body_is_redacted_before_exception() -> None:
    access = "".join(("ey", "Jsuper-secret-access-token-value-1234567890"))
    client_token = "".join(("bh", "_c_super-secret-client-token-value-1234567890"))

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            text=f"X-Access-Token: {access}; X-Client-Token={client_token}; Bearer another-secret-value",
        )

    with BetterHotelClient(Tokens("access", "client"), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BetterHotelError) as caught:
            client.get("/invoice")
    message = str(caught.value)
    assert access not in message
    assert client_token not in message
    assert "another-secret-value" not in message
    assert "REDACTED" in message
