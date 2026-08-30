from __future__ import annotations

import contextlib
import hashlib
import shutil
import sqlite3
import threading
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class DatabaseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: str


class Database:
    """SQLite connection factory with migrations, WAL and transaction boundaries."""

    def __init__(self, path: Path, migrations_dir: Path, backups_dir: Path) -> None:
        self.path = path
        self.migrations_dir = migrations_dir
        self.backups_dir = backups_dir
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    @contextlib.contextmanager
    def transaction(self, *, immediate: bool = True) -> Generator[sqlite3.Connection, None, None]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextlib.contextmanager
    def read_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def migrations(self) -> list[Migration]:
        result: list[Migration] = []
        for path in sorted(self.migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
            version = int(path.name.split("_", 1)[0])
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            result.append(Migration(version, path.stem, path, checksum))
        if not result:
            raise DatabaseError(f"Nenalezeny databázové migrace v {self.migrations_dir}")
        versions = [migration.version for migration in result]
        if len(versions) != len(set(versions)):
            raise DatabaseError("Adresář migrací obsahuje duplicitní číslo verze.")
        expected = list(range(versions[0], versions[-1] + 1))
        if versions != expected or versions[0] != 1:
            raise DatabaseError(f"Migrace musí tvořit souvislou řadu od 001; nalezeno {versions}.")
        return result

    def current_version(self) -> int:
        if not self.path.exists():
            return 0
        with self.read_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'"
            ).fetchone()
            if not exists:
                return 0
            row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migration").fetchone()
            return int(row["v"])

    def backup_before_migration(self) -> Path | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = self.backups_dir / f"pre-migration-{stamp}-{uuid4().hex[:8]}.sqlite3"
        source = self.connect()
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        return target

    def migrate(self) -> list[int]:
        available = self.migrations()
        current = self.current_version()
        if current:
            with self.read_connection() as conn:
                applied_rows = conn.execute(
                    "SELECT version,name,checksum FROM schema_migration ORDER BY version"
                ).fetchall()
            available_by_version = {migration.version: migration for migration in available}
            for row in applied_rows:
                migration = available_by_version.get(int(row["version"]))
                if migration is None:
                    raise DatabaseError(
                        f"Databáze obsahuje migraci {row['version']}, která v repozitáři chybí."
                    )
                if str(row["checksum"]) != migration.checksum:
                    raise DatabaseError(
                        f"Kontrolní součet již aplikované migrace {migration.path.name} se změnil."
                    )
        pending = [m for m in available if m.version > current]
        if not pending:
            return []
        self.backup_before_migration()
        applied: list[int] = []
        with self.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migration (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at_utc TEXT NOT NULL)"
            )
            for migration in pending:
                sql = migration.path.read_text(encoding="utf-8")
                # sqlite3.executescript commits implicitly. Execute statements manually so the outer
                # transaction remains authoritative and a failed migration fully rolls back.
                for statement in _split_sql_statements(sql):
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migration(version, name, checksum, applied_at_utc) VALUES (?, ?, ?, ?)",
                    (migration.version, migration.name, migration.checksum, _utc_now()),
                )
                applied.append(migration.version)
        self.integrity_check()
        return applied

    def integrity_check(self) -> None:
        with self.read_connection() as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        if result != "ok" or fk_rows:
            raise DatabaseError(f"Kontrola integrity databáze selhala: {result}; FK={len(fk_rows)}")

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(sql, tuple(params))
            return cursor.rowcount

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.read_connection() as conn:
            return list(conn.execute(sql, tuple(params)).fetchall())

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        with self.read_connection() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return None if row is None else row[0]

    def mark_startup(self) -> bool:
        """Return whether the previous shutdown was clean and mark this run unclean."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT value FROM app_runtime_state WHERE key='clean_shutdown'"
            ).fetchone()
            was_clean = row is None or row[0] == "1"
            conn.execute(
                "INSERT INTO app_runtime_state(key,value,updated_at_utc) VALUES('clean_shutdown','0',?) "
                "ON CONFLICT(key) DO UPDATE SET value='0', updated_at_utc=excluded.updated_at_utc",
                (_utc_now(),),
            )
        if not was_clean:
            self.integrity_check()
        return was_clean

    def mark_clean_shutdown(self) -> None:
        self.execute(
            "INSERT INTO app_runtime_state(key,value,updated_at_utc) VALUES('clean_shutdown','1',?) "
            "ON CONFLICT(key) DO UPDATE SET value='1', updated_at_utc=excluded.updated_at_utc",
            (_utc_now(),),
        )

    def clone_to(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _split_sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    in_trigger = False
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            in_trigger = True
        buffer.append(line)
        if in_trigger:
            if upper == "END;":
                statements.append("\n".join(buffer))
                buffer.clear()
                in_trigger = False
        elif stripped.endswith(";"):
            statements.append("\n".join(buffer))
            buffer.clear()
    if buffer:
        statements.append("\n".join(buffer))
    return statements
