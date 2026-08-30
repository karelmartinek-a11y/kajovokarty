from __future__ import annotations

import json
from uuid import uuid4

from kajovokarty.application.search import SearchService
from kajovokarty.infrastructure.persistence.database import Database


def test_appendix_b_technical_objects_are_live_search_results_and_related(database: Database) -> None:
    now = "2026-07-31T10:00:00Z"
    database.execute(
        "INSERT INTO reservation(uuid,internal_code,source_name,arrival,departure,booking_reference,reference_status,"
        "raw_json,content_hash,first_seen_utc,last_seen_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
        ("res-1", "120268038", "Booking.com", "2026-07-30", "2026-07-31", None, "CONFLICT", "{}", "rh", now, now),
    )
    database.execute(
        "INSERT INTO reservation_note_snapshot(id,reservation_id,raw_channel,redacted_preview,content_hash,fetched_at_utc) "
        "VALUES(?,?,?,?,?,?)",
        ("snap-1", "res-1", "Original ID: 6689102875", "Original ID: ••••••••", "sh", now),
    )
    database.execute(
        "INSERT INTO booking_reference_extraction(id,snapshot_id,reservation_id,candidate,label,start_offset,end_offset,"
        "status,parser_version,extracted_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("ref-1", "snap-1", "res-1", "6689102875", "Original ID", 13, 23, "CONFLICT", "1.1.0", now),
    )
    database.execute(
        "INSERT INTO bill(external_id,reservation_id,total_minor,balance_minor,currency_code,is_closed,is_locked,raw_json,"
        "content_hash,row_version) VALUES(?,?,?,?,?,?,?,?,?,1)",
        ("bill-1", "res-1", 10_000, 0, "EUR", 1, 0, "{}", "bh"),
    )
    database.execute(
        "INSERT INTO bill_item(external_id,bill_id,amount_minor,currency_code,raw_json,content_hash,row_version) "
        "VALUES(?,?,?,?,?,?,1)",
        ("item-1", "bill-1", 10_000, "EUR", "{}", "bih"),
    )
    database.execute(
        "INSERT INTO auto_match_candidate(id,currency_code,document_ids_json,source_refs_json,score,margin,difference_minor,"
        "evidence_json,alternatives_json,status,facts_hash,can_auto_match,created_at_utc,updated_at_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("cand-1", "EUR", "[]", "[]", 90, 10, 0, "{}", "[]", "CANDIDATE", "facts-1", 0, now, now),
    )
    database.execute(
        "INSERT INTO source_revision_alert(id,object_ref,previous_hash,current_hash,changed_fields_json,"
        "affected_group_ids_json,state,detected_at_utc) VALUES(?,?,?,?,?,?,?,?)",
        ("alert-1", "BILL:bill-1", "old", "new", json.dumps(["total"]), "[]", "OPEN", now),
    )

    service = SearchService(database)
    assert service.rebuild_index() == 6
    expected = {
        "BOOKING_REFERENCE:ref-1",
        "BILL:bill-1",
        "BILL_ITEM:item-1",
        "CANDIDATE:cand-1",
        "REVISION_ALERT:alert-1",
        "RESERVATION:res-1",
    }
    indexed = {row["object_ref"] for row in database.query("SELECT object_ref FROM global_search")}
    assert expected == indexed
    assert {item.object_ref for item in service.search("6689102875")} == {"BOOKING_REFERENCE:ref-1"}
    assert {item.object_ref for item in service.related("RESERVATION:res-1")} == {
        "BILL:bill-1",
        "BOOKING_REFERENCE:ref-1",
    }
    assert {item.object_ref for item in service.related("BILL:bill-1")} == {
        "RESERVATION:res-1",
        "BILL_ITEM:item-1",
    }
    assert {item.object_ref for item in service.related("REVISION_ALERT:alert-1")} == {"BILL:bill-1"}


def test_manual_source_relation_uses_manual_object_type(database: Database) -> None:
    now = "2026-07-31T10:00:00Z"
    group_id = uuid4().hex
    database.execute(
        "INSERT INTO match_group(id,currency_code,status,document_total_minor,source_total_minor,difference_minor,"
        "allocation_mode,manual_lock,source_revision_signature,created_at_utc,updated_at_utc,row_version) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
        (group_id, "CZK", "PARTIAL", 1000, 500, 500, "DETAILED", 1, "sig", now, now),
    )
    database.execute(
        "INSERT INTO manual_settlement(id,group_id,type,amount_minor,currency_code,name,note,active,created_at_utc,"
        "updated_at_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
        ("manual-1", group_id, "CASH", 500, "CZK", "Hotovost", None, 1, now, now),
    )
    service = SearchService(database)
    service.rebuild_index()
    assert [item.object_ref for item in service.related("MANUAL:manual-1")] == [f"MATCH_GROUP:{group_id}"]


def test_allocation_import_run_quarantine_and_audit_are_searchable_and_related(database: Database) -> None:
    now = "2026-07-31T10:00:00Z"
    database.execute(
        "INSERT INTO invoice(external_id,code,document_date_utc,total_minor,currency_code,pay_method,print_format,included,status,"
        "raw_json,content_hash,first_seen_utc,last_seen_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
        ("inv-1", "FA-1", now, 1000, "CZK", 2, 1, 1, "MANUAL_MATCHED", "{}", "ih", now, now),
    )
    database.execute(
        "INSERT INTO match_group(id,currency_code,status,document_total_minor,source_total_minor,difference_minor,"
        "allocation_mode,manual_lock,source_revision_signature,created_at_utc,updated_at_utc,row_version) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
        ("group-1", "CZK", "MANUAL_MATCHED", 1000, 1000, 0, "DETAILED", 1, "sig", now, now),
    )
    database.execute(
        "INSERT INTO allocation(id,group_id,source_type,source_id,invoice_id,amount_minor,method,command_id,active,"
        "created_at_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
        ("alloc-1", "group-1", "CARD", "card-1", "inv-1", 1000, "MANUAL", "cmd-1", 1, now),
    )
    database.execute(
        "INSERT INTO api_sync_run(id,correlation_id,state,counts_json,started_at_utc,heartbeat_at_utc,finished_at_utc) "
        "VALUES(?,?,?,?,?,?,?)",
        ("run-1", "corr-1", "SUCCEEDED", "{}", now, now, now),
    )
    database.execute(
        "INSERT INTO quarantined_source_row(id,run_type,run_id,row_no,raw_json,reason_code,reason_text,state,"
        "created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("quar-1", "API", "run-1", 7, "{}", "SCHEMA_DRIFT", "Neznámé pole", "OPEN", now, now),
    )
    database.execute(
        "INSERT INTO audit_event(event_id,correlation_id,event_code,operation_label,object_ref,windows_user,device_id,"
        "created_at_utc,redacted_context_json) VALUES(?,?,?,?,?,?,?,?,?)",
        ("event-1", "corr-1", "SYNC_DONE", "Synchronizace dokončena", "INVOICE:inv-1", "user", "device", now, "{}"),
    )

    service = SearchService(database)
    service.rebuild_index()
    indexed = {row["object_ref"] for row in database.query("SELECT object_ref FROM global_search")}
    assert {"ALLOCATION:alloc-1", "IMPORT_RUN:run-1", "QUARANTINE:quar-1", "AUDIT:event-1"} <= indexed
    assert {item.object_ref for item in service.related("IMPORT_RUN:run-1")} == {
        "QUARANTINE:quar-1",
        "AUDIT:event-1",
    }
    assert [item.object_ref for item in service.related("QUARANTINE:quar-1")] == ["IMPORT_RUN:run-1"]
    assert [item.object_ref for item in service.related("AUDIT:event-1")] == ["INVOICE:inv-1"]
