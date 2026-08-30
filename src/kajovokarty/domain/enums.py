from __future__ import annotations

from enum import StrEnum


class MatchStatus(StrEnum):
    UNMATCHED = "UNMATCHED"
    CANDIDATE = "CANDIDATE"
    AUTO_MATCHED = "AUTO_MATCHED"
    MANUAL_MATCHED = "MANUAL_MATCHED"
    PARTIAL = "PARTIAL"
    UNDERPAID = "UNDERPAID"
    OVERPAID = "OVERPAID"
    MANUAL_RESOLVED = "MANUAL_RESOLVED"
    CONFLICT = "CONFLICT"
    EXCLUDED = "EXCLUDED"
    REVERSED = "REVERSED"
    AGGREGATE_MATCHED = "AGGREGATE_MATCHED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class SourceType(StrEnum):
    BOOKING = "BOOKING"
    CARD = "CARD"
    CASH = "CASH"
    OTHER = "OTHER"


class AllocationMode(StrEnum):
    DETAILED = "DETAILED"
    AGGREGATE = "AGGREGATE"


class CandidateStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    OBSOLETE = "OBSOLETE"


class RunState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DUPLICATE = "DUPLICATE"


class QuarantineState(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class ObjectSide(StrEnum):
    DOCUMENT = "DOCUMENT"
    SOURCE = "SOURCE"
