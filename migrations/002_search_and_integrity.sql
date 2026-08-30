CREATE VIRTUAL TABLE IF NOT EXISTS global_search USING fts5(
    object_ref UNINDEXED,
    object_type UNINDEXED,
    primary_label,
    secondary_text,
    technical_ids,
    amount_text,
    date_text,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS app_runtime_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

INSERT OR IGNORE INTO app_runtime_state(key, value, updated_at_utc)
VALUES ('clean_shutdown', '1', strftime('%Y-%m-%dT%H:%M:%fZ','now'));
