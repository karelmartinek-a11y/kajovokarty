from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .enums import AllocationMode, CandidateStatus, MatchStatus, ObjectSide, SourceType


@dataclass(slots=True)
class Invoice:
    external_id: str
    code: str
    total_minor: int
    currency: str
    document_date: date
    paid_at: datetime | None = None
    pay_method: int | None = None
    print_format: int | None = None
    archived_at: datetime | None = None
    booking_reference: str | None = None
    internal_reservation_code: str | None = None
    included: bool = True
    row_version: int = 1
    status: MatchStatus = MatchStatus.UNMATCHED
    content_hash: str = ""

    @property
    def signed_total_minor(self) -> int:
        if self.print_format == 3 and self.total_minor > 0:
            return -self.total_minor
        return self.total_minor


@dataclass(slots=True)
class Reservation:
    uuid: str
    internal_code: str
    source_name: str | None
    arrival: date | None
    departure: date | None
    bill_id: str | None = None
    booking_reference: str | None = None
    reference_status: str | None = None
    row_version: int = 1
    content_hash: str = ""


@dataclass(slots=True)
class BookingPaymentLine:
    row_hash: str
    batch_natural_key: str
    payment_id: str
    booking_reference: str
    amount_minor: int
    currency: str
    payout_date: date
    arrival: date | None
    departure: date | None
    reservation_status: str
    payment_status: str
    guest_name: str | None = None
    status: MatchStatus = MatchStatus.UNMATCHED
    row_version: int = 1
    content_hash: str = ""

    @property
    def source_type(self) -> SourceType:
        return SourceType.BOOKING

    @property
    def source_id(self) -> str:
        return self.row_hash


@dataclass(slots=True)
class CardTransaction:
    terminal_id: str
    seq_id: str
    amount_minor: int
    currency: str
    occurred_at: datetime
    posted_date: date | None
    transaction_type: str
    server_at: datetime | None = None
    arn: str | None = None
    authorization_code: str | None = None
    masked_card: str | None = None
    variable_symbol: str | None = None
    variable_symbol_2: str | None = None
    cashback_minor: int = 0
    tip_minor: int = 0
    dcc_minor: int = 0
    status: MatchStatus = MatchStatus.UNMATCHED
    row_version: int = 1
    content_hash: str = ""

    @property
    def source_type(self) -> SourceType:
        return SourceType.CARD

    @property
    def source_id(self) -> str:
        return f"{self.terminal_id}|{self.seq_id}"


@dataclass(slots=True)
class ManualSettlement:
    id: str
    group_id: str
    source_type: SourceType
    amount_minor: int
    currency: str
    note: str | None
    created_at: datetime
    row_version: int = 1

    @property
    def source_id(self) -> str:
        return self.id


@dataclass(slots=True)
class MatchItem:
    entity_type: str
    entity_id: str
    side: ObjectSide
    amount_minor: int
    remaining_minor: int
    currency: str
    effective_date: date
    row_version: int = 1
    booking_reference: str | None = None
    internal_code: str | None = None
    paid_at: datetime | None = None
    manual_locked: bool = False
    status: MatchStatus = MatchStatus.UNMATCHED
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CandidateEvidence:
    code: str
    label: str
    score_delta: int
    detail: str
    conflicting: bool = False


@dataclass(slots=True)
class AutoMatchCandidate:
    id: str
    currency: str
    document_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    score: int
    margin: int
    difference_minor: int
    evidence: tuple[CandidateEvidence, ...]
    alternatives: tuple[str, ...] = ()
    status: CandidateStatus = CandidateStatus.PROPOSED
    facts_hash: str = ""
    can_auto_match: bool = False


@dataclass(slots=True)
class Allocation:
    id: str
    group_id: str
    source_type: SourceType
    source_id: str
    invoice_id: str
    amount_minor: int
    method: str
    command_id: str
    active: bool = True


@dataclass(slots=True)
class MatchGroupMember:
    group_id: str
    side: ObjectSide
    entity_type: str
    entity_id: str
    signed_amount_minor: int
    row_version: int = 1
    active: bool = True


@dataclass(slots=True)
class MatchGroup:
    id: str
    currency: str
    status: MatchStatus
    document_total_minor: int
    source_total_minor: int
    difference_minor: int
    allocation_mode: AllocationMode = AllocationMode.DETAILED
    manual_lock: bool = False
    source_revision_signature: str = ""
    review_required_reason: str | None = None
    row_version: int = 1
    allocations: list[Allocation] = field(default_factory=list)
    members: list[MatchGroupMember] = field(default_factory=list)


@dataclass(slots=True)
class BookingReferenceExtraction:
    candidate: str
    label: str
    start_offset: int
    end_offset: int
    reservation_uuid: str
    parser_version: str
    status: str
    raw_snapshot_hash: str
