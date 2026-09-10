CREATE TABLE IF NOT EXISTS match_group_child (
    parent_group_id TEXT NOT NULL REFERENCES match_group(id) ON DELETE CASCADE,
    child_group_id TEXT NOT NULL REFERENCES match_group(id) ON DELETE RESTRICT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at_utc TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(parent_group_id, child_group_id),
    CHECK(parent_group_id <> child_group_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_match_group_active_parent ON match_group_child(child_group_id) WHERE active=1;
CREATE INDEX IF NOT EXISTS ix_match_group_children_parent ON match_group_child(parent_group_id, active);
