PRAGMA foreign_keys = ON;

ALTER TABLE booking_payment_line ADD COLUMN payout_date TEXT;
ALTER TABLE booking_payment_line ADD COLUMN source_identity TEXT;
ALTER TABLE booking_payment_line ADD COLUMN active_source INTEGER NOT NULL DEFAULT 1 CHECK (active_source IN (0,1));
CREATE INDEX IF NOT EXISTS ix_booking_line_identity ON booking_payment_line(source_identity, active_source);
CREATE INDEX IF NOT EXISTS ix_booking_line_payout_date ON booking_payment_line(payout_date);

ALTER TABLE quarantined_source_row ADD COLUMN resolved_at_utc TEXT;
ALTER TABLE quarantined_source_row ADD COLUMN resolution_method TEXT;

ALTER TABLE source_revision_alert ADD COLUMN resolution_method TEXT;
ALTER TABLE source_revision_alert ADD COLUMN resolution_note TEXT;

CREATE TABLE IF NOT EXISTS booking_line_revision (
    id TEXT PRIMARY KEY,
    source_identity TEXT NOT NULL,
    previous_row_hash TEXT NOT NULL REFERENCES booking_payment_line(row_hash) ON DELETE RESTRICT,
    current_row_hash TEXT NOT NULL REFERENCES booking_payment_line(row_hash) ON DELETE RESTRICT,
    changed_fields_json TEXT NOT NULL,
    detected_at_utc TEXT NOT NULL,
    UNIQUE(previous_row_hash, current_row_hash)
);
CREATE INDEX IF NOT EXISTS ix_booking_revision_identity ON booking_line_revision(source_identity, detected_at_utc DESC);

CREATE TABLE IF NOT EXISTS api_raw_snapshot (
    id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    correlation_id TEXT,
    UNIQUE(resource_type, external_id, content_hash)
);
CREATE INDEX IF NOT EXISTS ix_api_raw_snapshot_object ON api_raw_snapshot(resource_type, external_id, fetched_at_utc DESC);

CREATE TABLE IF NOT EXISTS security_deposit (
    external_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL REFERENCES reservation(uuid) ON DELETE CASCADE,
    amount_minor INTEGER NOT NULL,
    currency_code TEXT NOT NULL,
    status TEXT,
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_security_deposit_reservation ON security_deposit(reservation_id);

CREATE TABLE IF NOT EXISTS financial_stats_snapshot (
    id TEXT PRIMARY KEY,
    range_start TEXT,
    range_end TEXT,
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    correlation_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_financial_stats_fetched ON financial_stats_snapshot(fetched_at_utc DESC);
