ALTER TABLE operation_run ADD COLUMN recovery_json TEXT NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS ix_operation_interrupted ON operation_run(state, started_at_utc DESC);
