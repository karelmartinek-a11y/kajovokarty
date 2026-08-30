from __future__ import annotations

from kajovokarty.application.audit import AuditService
from kajovokarty.application.reference_resolution import BookingReferenceResolutionService
from kajovokarty.infrastructure.persistence.database import Database


def _seed_conflict(database: Database) -> None:
    now = "2026-07-31T10:00:00Z"
    database.execute(
        "INSERT INTO reservation(uuid,internal_code,source_name,booking_reference,reference_status,raw_json,content_hash,"
        "first_seen_utc,last_seen_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,1)",
        ("res-1", "120268038", "Booking.com", None, "CONFLICT", "{}", "rhash", now, now),
    )
    database.execute(
        "INSERT INTO reservation_note_snapshot(id,reservation_id,raw_channel,redacted_preview,content_hash,fetched_at_utc) "
        "VALUES(?,?,?,?,?,?)",
        ("snap-1", "res-1", "Original ID: 6689102875 / Channel reservation id: 6689102999", "redacted", "sh", now),
    )
    for extraction_id, candidate, label in (
        ("ref-1", "6689102875", "Original ID"),
        ("ref-2", "6689102999", "Channel reservation id"),
    ):
        database.execute(
            "INSERT INTO booking_reference_extraction(id,snapshot_id,reservation_id,candidate,label,start_offset,end_offset,"
            "status,parser_version,extracted_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (extraction_id, "snap-1", "res-1", candidate, label, 0, 10, "CONFLICT", "1.1.0", now),
        )


def test_confirm_booking_reference_is_audited_and_reversible(database: Database) -> None:
    _seed_conflict(database)
    service = BookingReferenceResolutionService(database, AuditService())
    result = service.confirm("ref-1")
    assert result.candidate == "6689102875"
    assert database.scalar("SELECT booking_reference FROM reservation WHERE uuid='res-1'") == "6689102875"
    assert database.scalar("SELECT reference_status FROM reservation WHERE uuid='res-1'") == "MANUAL_CONFIRMED"
    assert database.scalar("SELECT status FROM booking_reference_extraction WHERE id='ref-1'") == "MANUAL_CONFIRMED"
    assert database.scalar("SELECT status FROM booking_reference_extraction WHERE id='ref-2'") == "MANUAL_REJECTED"
    assert database.scalar("SELECT COUNT(*) FROM audit_event WHERE event_code='BOOKING_REFERENCE_CONFIRMED'") == 1

    service.undo(result.command_id)
    assert database.scalar("SELECT booking_reference FROM reservation WHERE uuid='res-1'") is None
    assert database.scalar("SELECT reference_status FROM reservation WHERE uuid='res-1'") == "CONFLICT"
    assert database.scalar("SELECT status FROM booking_reference_extraction WHERE id='ref-1'") == "CONFLICT"
    assert database.scalar("SELECT status FROM booking_reference_extraction WHERE id='ref-2'") == "CONFLICT"
    assert database.scalar("SELECT COUNT(*) FROM audit_event WHERE event_code='BOOKING_REFERENCE_UNDO'") == 1


def test_reject_one_booking_reference_preserves_remaining_candidate(database: Database) -> None:
    _seed_conflict(database)
    service = BookingReferenceResolutionService(database, AuditService())
    result = service.reject("ref-2")
    assert result.status == "MANUAL_CONFIRMED"
    assert database.scalar("SELECT booking_reference FROM reservation WHERE uuid='res-1'") == "6689102875"
    assert database.scalar("SELECT status FROM booking_reference_extraction WHERE id='ref-2'") == "MANUAL_REJECTED"
