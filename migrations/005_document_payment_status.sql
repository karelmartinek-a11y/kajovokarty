CREATE TABLE IF NOT EXISTS invoice_payment_status (
    invoice_id TEXT PRIMARY KEY REFERENCES invoice(external_id) ON DELETE CASCADE,
    manual_paid INTEGER NOT NULL DEFAULT 0 CHECK (manual_paid IN (0,1)),
    manual_paid_at_utc TEXT,
    manual_paid_by TEXT,
    updated_at_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS payment_matching_alert (
    id TEXT PRIMARY KEY,
    invoice_id TEXT REFERENCES invoice(external_id) ON DELETE CASCADE,
    severity TEXT NOT NULL DEFAULT 'INFO',
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    source_id TEXT,
    created_at_utc TEXT NOT NULL,
    resolved_at_utc TEXT
);

CREATE INDEX IF NOT EXISTS ix_payment_alert_open ON payment_matching_alert(severity, resolved_at_utc, created_at_utc);
CREATE INDEX IF NOT EXISTS ix_payment_alert_invoice ON payment_matching_alert(invoice_id, resolved_at_utc);
