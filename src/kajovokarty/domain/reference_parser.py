from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from .entities import BookingReferenceExtraction

PARSER_VERSION = "1.1.0"
_PATTERN = re.compile(r"(?i)(Original\s*ID|Channel\s*reservation\s*id)\s*[:=]?\s*([0-9]{6,20})")


@dataclass(frozen=True, slots=True)
class BookingReferenceResult:
    confirmed: str | None
    status: str
    values: tuple[str, ...]
    candidates: tuple[BookingReferenceExtraction, ...]
    parsed_at: datetime

    @property
    def confirmed_candidate(self) -> str | None:
        return self.confirmed

    @property
    def extractions(self) -> tuple[BookingReferenceExtraction, ...]:
        return self.candidates


def normalize_channel(raw: str) -> str:
    value = unicodedata.normalize("NFC", html.unescape(raw or ""))
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"</?[^>]+>", " ", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\t ]+", " ", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def extract_booking_reference(reservation_uuid: str, channels: Iterable[str]) -> BookingReferenceResult:
    extractions: list[BookingReferenceExtraction] = []
    values: list[str] = []
    for raw in channels:
        normalized = normalize_channel(raw)
        snapshot_hash = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
        for match in _PATTERN.finditer(normalized):
            label, candidate = match.group(1), match.group(2)
            values.append(candidate)
            extractions.append(
                BookingReferenceExtraction(
                    candidate=candidate,
                    label=label,
                    start_offset=match.start(2),
                    end_offset=match.end(2),
                    reservation_uuid=reservation_uuid,
                    parser_version=PARSER_VERSION,
                    status="FOUND",
                    raw_snapshot_hash=snapshot_hash,
                )
            )
    unique = tuple(dict.fromkeys(values))
    status = "MISSING" if not unique else "CONFIRMED" if len(unique) == 1 else "CONFLICT"
    confirmed = unique[0] if status == "CONFIRMED" else None
    for item in extractions:
        item.status = status
    return BookingReferenceResult(confirmed, status, unique, tuple(extractions), datetime.now(UTC))


class ReservationReferenceParser:
    version = PARSER_VERSION

    def extract(self, reservation_uuid: str, channels: Iterable[str]) -> BookingReferenceResult:
        return extract_booking_reference(reservation_uuid, channels)

    def parse(self, channels: Iterable[str], *, reservation_uuid: str) -> BookingReferenceResult:
        """UI/test friendly alias preserving the normative all-channel extraction contract."""
        return self.extract(reservation_uuid, channels)

    @staticmethod
    def redacted_preview(raw: str) -> str:
        normalized = normalize_channel(raw)
        normalized = re.sub(r"(?<!\d)\d{3,}(?!\d)", lambda match: "•" * min(8, len(match.group(0))), normalized)
        normalized = re.sub(r"(?i)([\w.+-]+)@([\w.-]+)", "•••@•••", normalized)
        return normalized[:240]
