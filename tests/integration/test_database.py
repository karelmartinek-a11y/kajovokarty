import sqlite3
from pathlib import Path

import pytest

from kajovokarty.application.audit import AuditContext, AuditService
from kajovokarty.infrastructure.persistence.database import Database, DatabaseError


def test_migrations_enable_wal_foreign_keys_and_integrity(database: Database) -> None:
    with database.read_connection() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert database.current_version() == 7


def test_audit_is_append_only(database: Database) -> None:
    audit = AuditService()
    with database.transaction() as conn:
        event_id = audit.append(conn, event_code="TEST", operation_label="Test", context=AuditContext("corr"), object_ref="TEST:1", before={"a": 1}, after={"a": 2})
    with pytest.raises(sqlite3.DatabaseError):
        database.execute("DELETE FROM audit_event WHERE event_id=?", (event_id,))
    row = database.query("SELECT before_json,after_json FROM audit_event WHERE event_id=?", (event_id,))[0]
    assert '"a": 1' in row["before_json"]
    assert '"a": 2' in row["after_json"]


def test_failed_transaction_leaves_no_partial_command(database: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as conn:
            conn.execute("INSERT INTO currency(external_id,iso_code,raw_json,content_hash,updated_at_utc) VALUES('1','CZK','{}','h','now')")
            conn.execute("INSERT INTO currency(external_id,iso_code,raw_json,content_hash,updated_at_utc) VALUES('2','CZK','{}','h2','now')")
    assert database.scalar("SELECT COUNT(*) FROM currency") == 0


def test_backup_is_created_before_pending_migration(tmp_path: Path, database: Database) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    for source in database.migrations_dir.glob("*.sql"):
        (migration_dir / source.name).write_bytes(source.read_bytes())
    (migration_dir / "008_probe.sql").write_text("CREATE TABLE migration_probe(id INTEGER PRIMARY KEY);", encoding="utf-8")
    migrated = Database(database.path, migration_dir, database.backups_dir)
    assert migrated.migrate() == [8]
    assert list(database.backups_dir.glob("pre-migration-*.sqlite3"))


def test_applied_migration_checksum_change_is_rejected(tmp_path: Path, database: Database) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    for source in database.migrations_dir.glob("*.sql"):
        (migration_dir / source.name).write_bytes(source.read_bytes())
    target = migration_dir / "002_search_and_integrity.sql"
    target.write_text(target.read_text(encoding="utf-8") + "\n-- forbidden rewrite\n", encoding="utf-8")
    migrated = Database(database.path, migration_dir, database.backups_dir)
    with pytest.raises(DatabaseError, match="Kontrolní součet"):
        migrated.migrate()


def test_migration_version_gap_is_rejected(tmp_path: Path, database: Database) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_initial.sql").write_text("CREATE TABLE a(id INTEGER);", encoding="utf-8")
    (migration_dir / "003_gap.sql").write_text("CREATE TABLE b(id INTEGER);", encoding="utf-8")
    isolated = Database(tmp_path / "gap.sqlite3", migration_dir, tmp_path / "backups")
    with pytest.raises(DatabaseError, match="souvislou řadu"):
        isolated.migrate()
