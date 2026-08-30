from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from ...domain.money import MoneyError, normalize_currency, to_minor


class BetterHotelDataError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BetterHotelDataError(f"Neplatný RFC 3339 timestamp: {value!r}") from exc
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def timestamp_text(value: Any) -> str | None:
    parsed = parse_timestamp(value)
    return None if parsed is None else parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def normalize_paid(payload: dict[str, Any]) -> str | None:
    paid = parse_timestamp(payload.get("paid"))
    payed = parse_timestamp(payload.get("payed"))
    if paid is None:
        chosen = payed
    elif payed is None:
        chosen = paid
    elif abs((paid - payed).total_seconds()) < 0.001:
        chosen = min(paid, payed)
    else:
        chosen = paid
    return None if chosen is None else chosen.isoformat(timespec="microseconds").replace("+00:00", "Z")


def normalize_internal_code(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, ".15g")
    text = str(value).strip()
    if text.endswith(".0"):
        head = text[:-2]
        if head.lstrip("-").isdigit():
            return head
    return text


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def currency_code(value: Any, currency_map: dict[str, str]) -> str:
    key = str(value).strip()
    if key in currency_map:
        return currency_map[key]
    try:
        return normalize_currency(key)
    except MoneyError as exc:
        raise BetterHotelDataError(f"Neznámá měna Better Hotel: {value!r}") from exc


def amount_minor(value: Any, code: str) -> int:
    if value is None or value == "":
        return 0
    return to_minor(value, code)


@dataclass(frozen=True, slots=True)
class InvoiceDTO:
    external_id: str
    document_uuid: str | None
    code: str
    document_date_utc: str
    due_date_utc: str | None
    vat_date_utc: str | None
    paid_at_utc: str | None
    archived_at_utc: str | None
    total_minor: int
    subtotal_minor: int
    deposit_minor: int
    currency_code: str
    pay_method: int | None
    print_format: int | None
    exchange_rate: str | None
    vat_exchange_rate: str | None
    raw_json: str
    content_hash: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any], currencies: dict[str, str]) -> InvoiceDTO:
        external_id = str(payload.get("id") or "").strip()
        if not external_id:
            raise BetterHotelDataError("Faktura nemá stabilní id.")
        code = str(payload.get("code") or payload.get("number") or external_id).strip()
        document_date = timestamp_text(payload.get("date"))
        if document_date is None:
            raise BetterHotelDataError(f"Faktura {external_id} nemá datum.")
        currency = currency_code(payload.get("currency"), currencies)
        total = amount_minor(payload.get("total"), currency)
        print_format = as_int(payload.get("print_format"))
        if print_format == 3 and total > 0:
            total = -total
        return cls(
            external_id=external_id,
            document_uuid=str(payload.get("document_uuid") or "").strip() or None,
            code=code,
            document_date_utc=document_date,
            due_date_utc=timestamp_text(payload.get("due_date")),
            vat_date_utc=timestamp_text(payload.get("vat_date")),
            paid_at_utc=normalize_paid(payload),
            archived_at_utc=timestamp_text(payload.get("archived")),
            total_minor=total,
            subtotal_minor=amount_minor(payload.get("subtotal"), currency),
            deposit_minor=amount_minor(payload.get("deposit"), currency),
            currency_code=currency,
            pay_method=as_int(payload.get("pay_method")),
            print_format=print_format,
            exchange_rate=None if payload.get("exchange_rate") is None else str(Decimal(str(payload["exchange_rate"]))),
            vat_exchange_rate=None if payload.get("vat_exchange_rate") is None else str(Decimal(str(payload["vat_exchange_rate"]))),
            raw_json=canonical_json(payload),
            content_hash=content_hash(payload),
        )


@dataclass(frozen=True, slots=True)
class ReservationDTO:
    uuid: str
    internal_code: str
    source_id: str | None
    source_name: str | None
    arrival: str | None
    departure: str | None
    bill_id: str | None
    raw_json: str
    content_hash: str
    channels: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ReservationDTO:
        uuid = str(payload.get("id") or payload.get("uuid") or "").strip()
        if not uuid:
            raise BetterHotelDataError("Rezervace nemá UUID.")
        source = payload.get("reservation_source")
        if not isinstance(source, dict):
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        notes = payload.get("reservation_note")
        if not isinstance(notes, list):
            notes = []
        channels = tuple(
            str(note.get("channel"))
            for note in notes
            if isinstance(note, dict) and note.get("channel") not in (None, "")
        )
        return cls(
            uuid=uuid,
            internal_code=normalize_internal_code(payload.get("code")),
            source_id=str(source.get("id") or "").strip() or None,
            source_name=str(source.get("name") or "").strip() or None,
            arrival=_date_text(payload.get("arrival") or payload.get("date_from")),
            departure=_date_text(payload.get("departure") or payload.get("date_to")),
            bill_id=str(payload.get("bill_id") or "").strip() or None,
            raw_json=canonical_json(payload),
            content_hash=content_hash(payload),
            channels=channels,
        )


def _date_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        timestamp = parse_timestamp(value)
        return None if timestamp is None else timestamp.date().isoformat()
