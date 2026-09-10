CREATE TABLE IF NOT EXISTS cashbook_import_run (
    id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    totals_json TEXT NOT NULL,
    error_json TEXT,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT
);
CREATE INDEX IF NOT EXISTS ix_cashbook_import_hash ON cashbook_import_run(file_hash);

CREATE TABLE IF NOT EXISTS cashbook_card_transaction (
    id TEXT PRIMARY KEY,
    cashbook_identity TEXT NOT NULL UNIQUE,
    occurred_at TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('INCOME','EXPENSE')),
    amount_minor INTEGER NOT NULL CHECK(amount_minor <> 0),
    currency_code TEXT NOT NULL CHECK(currency_code IN ('CZK','EUR')),
    receipt_number TEXT NOT NULL,
    label TEXT NOT NULL,
    client TEXT,
    payment_form TEXT NOT NULL,
    cashbox TEXT,
    variable_symbol TEXT,
    issued_by TEXT,
    status TEXT NOT NULL DEFAULT 'UNMATCHED',
    raw_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_cashbook_card_date ON cashbook_card_transaction(occurred_at);
CREATE INDEX IF NOT EXISTS ix_cashbook_card_amount ON cashbook_card_transaction(currency_code, amount_minor);
