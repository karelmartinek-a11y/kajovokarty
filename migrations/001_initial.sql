PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    typed_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_sync_run (
    id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    range_start TEXT,
    range_end TEXT,
    counts_json TEXT NOT NULL DEFAULT '{}',
    error_json TEXT,
    started_at_utc TEXT NOT NULL,
    heartbeat_at_utc TEXT NOT NULL,
    finished_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS ix_api_sync_run_started ON api_sync_run(started_at_utc DESC);

CREATE TABLE IF NOT EXISTS api_checkpoint (
    resource TEXT PRIMARY KEY,
    checkpoint_utc TEXT NOT NULL,
    overlap_seconds INTEGER NOT NULL DEFAULT 172800,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS currency (
    external_id TEXT PRIMARY KEY,
    iso_code TEXT NOT NULL UNIQUE,
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoice (
    external_id TEXT PRIMARY KEY,
    document_uuid TEXT,
    code TEXT NOT NULL,
    document_date_utc TEXT NOT NULL,
    due_date_utc TEXT,
    vat_date_utc TEXT,
    paid_at_utc TEXT,
    archived_at_utc TEXT,
    total_minor INTEGER NOT NULL,
    subtotal_minor INTEGER,
    deposit_minor INTEGER,
    currency_code TEXT NOT NULL,
    pay_method INTEGER,
    print_format INTEGER,
    exchange_rate TEXT,
    vat_exchange_rate TEXT,
    included INTEGER NOT NULL DEFAULT 1 CHECK (included IN (0,1)),
    status TEXT NOT NULL DEFAULT 'UNMATCHED',
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_invoice_code ON invoice(code);
CREATE INDEX IF NOT EXISTS ix_invoice_paid ON invoice(paid_at_utc);
CREATE INDEX IF NOT EXISTS ix_invoice_currency_status ON invoice(currency_code, status);

CREATE TABLE IF NOT EXISTS invoice_item (
    external_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL REFERENCES invoice(external_id) ON DELETE CASCADE,
    bill_item_id TEXT,
    signed_amount_minor INTEGER NOT NULL,
    currency_code TEXT NOT NULL,
    vat_type TEXT,
    service_from TEXT,
    service_to TEXT,
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_invoice_item_invoice ON invoice_item(invoice_id);
CREATE INDEX IF NOT EXISTS ix_invoice_item_bill_item ON invoice_item(bill_item_id);

CREATE TABLE IF NOT EXISTS reservation (
    uuid TEXT PRIMARY KEY,
    internal_code TEXT NOT NULL,
    source_id TEXT,
    source_name TEXT,
    arrival TEXT,
    departure TEXT,
    bill_id TEXT,
    booking_reference TEXT,
    reference_status TEXT,
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_reservation_code ON reservation(internal_code);
CREATE INDEX IF NOT EXISTS ix_reservation_source_dates ON reservation(source_name, arrival, departure);
CREATE INDEX IF NOT EXISTS ix_reservation_booking_ref ON reservation(booking_reference);

CREATE TABLE IF NOT EXISTS reservation_note_snapshot (
    id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL REFERENCES reservation(uuid) ON DELETE CASCADE,
    raw_channel TEXT NOT NULL,
    redacted_preview TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    UNIQUE(reservation_id, content_hash)
);
CREATE INDEX IF NOT EXISTS ix_reservation_note_reservation ON reservation_note_snapshot(reservation_id);

CREATE TABLE IF NOT EXISTS booking_reference_extraction (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES reservation_note_snapshot(id) ON DELETE CASCADE,
    reservation_id TEXT NOT NULL REFERENCES reservation(uuid) ON DELETE CASCADE,
    candidate TEXT NOT NULL,
    label TEXT NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    status TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    extracted_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_booking_extraction_candidate ON booking_reference_extraction(candidate);
CREATE INDEX IF NOT EXISTS ix_booking_extraction_reservation ON booking_reference_extraction(reservation_id);

CREATE TABLE IF NOT EXISTS reservation_group (
    id TEXT PRIMARY KEY,
    internal_code TEXT NOT NULL,
    booking_reference TEXT,
    row_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(internal_code, booking_reference)
);
CREATE INDEX IF NOT EXISTS ix_reservation_group_code ON reservation_group(internal_code);
CREATE INDEX IF NOT EXISTS ix_reservation_group_booking ON reservation_group(booking_reference);

CREATE TABLE IF NOT EXISTS reservation_group_member (
    group_id TEXT NOT NULL REFERENCES reservation_group(id) ON DELETE CASCADE,
    reservation_id TEXT NOT NULL REFERENCES reservation(uuid) ON DELETE CASCADE,
    PRIMARY KEY(group_id, reservation_id),
    UNIQUE(reservation_id)
);

CREATE TABLE IF NOT EXISTS reservation_invoice_link (
    reservation_id TEXT NOT NULL REFERENCES reservation(uuid) ON DELETE CASCADE,
    invoice_id TEXT NOT NULL REFERENCES invoice(external_id) ON DELETE CASCADE,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    PRIMARY KEY(reservation_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS bill (
    external_id TEXT PRIMARY KEY,
    reservation_id TEXT,
    total_minor INTEGER,
    balance_minor INTEGER,
    currency_code TEXT,
    is_closed INTEGER,
    is_locked INTEGER,
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_bill_reservation ON bill(reservation_id);

CREATE TABLE IF NOT EXISTS bill_item (
    external_id TEXT PRIMARY KEY,
    bill_id TEXT NOT NULL REFERENCES bill(external_id) ON DELETE CASCADE,
    amount_minor INTEGER NOT NULL,
    currency_code TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_bill_item_bill ON bill_item(bill_id);

CREATE TABLE IF NOT EXISTS booking_import_run (
    id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    totals_json TEXT NOT NULL,
    error_json TEXT,
    started_at_utc TEXT NOT NULL,
    heartbeat_at_utc TEXT NOT NULL,
    finished_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS ix_booking_import_hash ON booking_import_run(file_hash);

CREATE TABLE IF NOT EXISTS booking_payout_batch (
    id TEXT PRIMARY KEY,
    natural_key TEXT NOT NULL UNIQUE,
    payment_id TEXT NOT NULL,
    payout_date TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS booking_payment_line (
    row_hash TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES booking_payout_batch(id) ON DELETE RESTRICT,
    booking_reference TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency_code TEXT NOT NULL,
    arrival TEXT,
    departure TEXT,
    guest_name TEXT,
    provider TEXT,
    reservation_status TEXT NOT NULL,
    payment_status TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'UNMATCHED',
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_booking_line_reference ON booking_payment_line(booking_reference);
CREATE INDEX IF NOT EXISTS ix_booking_line_currency_status ON booking_payment_line(currency_code, status);

CREATE TABLE IF NOT EXISTS bank_import_run (
    id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    totals_json TEXT NOT NULL,
    source_summary_json TEXT NOT NULL,
    error_json TEXT,
    started_at_utc TEXT NOT NULL,
    heartbeat_at_utc TEXT NOT NULL,
    finished_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS ix_bank_import_hash ON bank_import_run(file_hash);

CREATE TABLE IF NOT EXISTS card_transaction (
    id TEXT PRIMARY KEY,
    terminal_id TEXT NOT NULL,
    seq_id TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    server_at TEXT,
    posted_date TEXT,
    amount_minor INTEGER NOT NULL,
    currency_code TEXT NOT NULL,
    cashback_minor INTEGER NOT NULL DEFAULT 0,
    tip_minor INTEGER NOT NULL DEFAULT 0,
    dcc_minor INTEGER NOT NULL DEFAULT 0,
    arn TEXT,
    authorization_code TEXT,
    masked_card TEXT,
    variable_symbol TEXT,
    variable_symbol_2 TEXT,
    issuer TEXT,
    read_method TEXT,
    merchant_place TEXT,
    merchant_address TEXT,
    status TEXT NOT NULL DEFAULT 'UNMATCHED',
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(terminal_id, seq_id)
);
CREATE INDEX IF NOT EXISTS ix_card_transaction_dates ON card_transaction(occurred_at, posted_date);
CREATE INDEX IF NOT EXISTS ix_card_transaction_amount ON card_transaction(currency_code, amount_minor);
CREATE INDEX IF NOT EXISTS ix_card_transaction_refs ON card_transaction(arn, authorization_code, variable_symbol);

CREATE TABLE IF NOT EXISTS quarantined_source_row (
    id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    run_id TEXT NOT NULL,
    row_no INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    reason_text TEXT NOT NULL,
    resolution_json TEXT,
    state TEXT NOT NULL DEFAULT 'OPEN',
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE(run_type, run_id, row_no, reason_code)
);
CREATE INDEX IF NOT EXISTS ix_quarantine_run ON quarantined_source_row(run_id, reason_code);
CREATE INDEX IF NOT EXISTS ix_quarantine_state ON quarantined_source_row(state);

CREATE TABLE IF NOT EXISTS import_value_mapping (
    source_kind TEXT NOT NULL,
    field_name TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    mapped_meaning TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(source_kind, field_name, raw_value)
);

CREATE TABLE IF NOT EXISTS match_group (
    id TEXT PRIMARY KEY,
    currency_code TEXT NOT NULL,
    status TEXT NOT NULL,
    document_total_minor INTEGER NOT NULL,
    source_total_minor INTEGER NOT NULL,
    difference_minor INTEGER NOT NULL,
    allocation_mode TEXT NOT NULL DEFAULT 'DETAILED',
    manual_lock INTEGER NOT NULL DEFAULT 0 CHECK (manual_lock IN (0,1)),
    source_revision_signature TEXT NOT NULL,
    review_required_reason TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_match_group_status_currency ON match_group(status, currency_code, updated_at_utc);

CREATE TABLE IF NOT EXISTS match_group_document (
    group_id TEXT NOT NULL REFERENCES match_group(id) ON DELETE CASCADE,
    invoice_id TEXT NOT NULL REFERENCES invoice(external_id) ON DELETE RESTRICT,
    signed_amount_minor INTEGER NOT NULL,
    first_seen_utc TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    row_version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(group_id, invoice_id)
);
CREATE INDEX IF NOT EXISTS ix_match_document_invoice ON match_group_document(invoice_id, active);

CREATE TABLE IF NOT EXISTS match_group_source (
    group_id TEXT NOT NULL REFERENCES match_group(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    signed_amount_minor INTEGER NOT NULL,
    first_seen_utc TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    row_version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(group_id, entity_type, entity_id)
);
CREATE INDEX IF NOT EXISTS ix_match_source_entity ON match_group_source(entity_type, entity_id, active);

CREATE TABLE IF NOT EXISTS allocation (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES match_group(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL REFERENCES invoice(external_id) ON DELETE RESTRICT,
    amount_minor INTEGER NOT NULL,
    method TEXT NOT NULL,
    command_id TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_allocation_group ON allocation(group_id, active);
CREATE INDEX IF NOT EXISTS ix_allocation_invoice ON allocation(invoice_id, active);
CREATE INDEX IF NOT EXISTS ix_allocation_source ON allocation(source_type, source_id, active);

CREATE TABLE IF NOT EXISTS manual_settlement (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES match_group(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency_code TEXT NOT NULL,
    name TEXT,
    note TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_manual_settlement_group ON manual_settlement(group_id, active);

CREATE TABLE IF NOT EXISTS auto_match_candidate (
    id TEXT PRIMARY KEY,
    currency_code TEXT NOT NULL,
    document_ids_json TEXT NOT NULL,
    source_refs_json TEXT NOT NULL,
    score INTEGER NOT NULL,
    margin INTEGER NOT NULL,
    difference_minor INTEGER NOT NULL,
    evidence_json TEXT NOT NULL,
    alternatives_json TEXT NOT NULL,
    status TEXT NOT NULL,
    facts_hash TEXT NOT NULL,
    can_auto_match INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE(facts_hash, document_ids_json, source_refs_json)
);
CREATE INDEX IF NOT EXISTS ix_candidate_status_score ON auto_match_candidate(status, score DESC);

CREATE TABLE IF NOT EXISTS rejected_candidate_fact (
    facts_hash TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    rejected_at_utc TEXT NOT NULL,
    command_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_revision_alert (
    id TEXT PRIMARY KEY,
    object_ref TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    current_hash TEXT NOT NULL,
    changed_fields_json TEXT NOT NULL,
    affected_group_ids_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'OPEN',
    detected_at_utc TEXT NOT NULL,
    resolved_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS ix_revision_alert_object ON source_revision_alert(object_ref, state, detected_at_utc);

CREATE TABLE IF NOT EXISTS action_command (
    command_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    command_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    inverse_payload_json TEXT,
    human_label TEXT NOT NULL,
    reversible INTEGER NOT NULL CHECK (reversible IN (0,1)),
    state TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    applied_at_utc TEXT,
    reversed_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS ix_action_command_created ON action_command(created_at_utc DESC, state);

CREATE TABLE IF NOT EXISTS audit_event (
    event_id TEXT PRIMARY KEY,
    command_id TEXT,
    correlation_id TEXT NOT NULL,
    event_code TEXT NOT NULL,
    operation_label TEXT NOT NULL,
    object_ref TEXT,
    before_json TEXT,
    after_json TEXT,
    windows_user TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    local_time_zone TEXT NOT NULL DEFAULT 'Europe/Prague',
    redacted_context_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(command_id) REFERENCES action_command(command_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_audit_object_time ON audit_event(object_ref, created_at_utc DESC);
CREATE INDEX IF NOT EXISTS ix_audit_command ON audit_event(command_id);
CREATE INDEX IF NOT EXISTS ix_audit_correlation ON audit_event(correlation_id);

CREATE TRIGGER IF NOT EXISTS audit_event_no_update
BEFORE UPDATE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_event_no_delete
BEFORE DELETE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event is append-only');
END;

CREATE TABLE IF NOT EXISTS user_view_state (
    view_key TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_filter (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    view_key TEXT NOT NULL,
    filter_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backup_record (
    id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    database_hash TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    verified_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS ix_backup_created ON backup_record(created_at_utc DESC);

CREATE TABLE IF NOT EXISTS diagnostic_run (
    id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    state TEXT NOT NULL,
    output_path TEXT,
    summary_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    finished_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS operation_run (
    id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    state TEXT NOT NULL,
    step TEXT NOT NULL,
    current_count INTEGER,
    total_count INTEGER,
    message TEXT NOT NULL,
    heartbeat_at_utc TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    error_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_operation_state ON operation_run(state, heartbeat_at_utc DESC);
