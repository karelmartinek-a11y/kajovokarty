from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kajovokarty.app.paths import AppPaths
from kajovokarty.infrastructure.persistence.database import Database


@pytest.fixture()
def app_paths(tmp_path: Path) -> AppPaths:
    data = tmp_path / "data"
    paths = AppPaths(
        root=ROOT,
        data=data,
        database=data / "kajovokarty.sqlite3",
        logs=data / "logs",
        backups=data / "backups",
        exports=data / "exports",
        diagnostics=data / "diagnostics",
        resources=ROOT / "resources",
        migrations=ROOT / "migrations",
    )
    paths.ensure()
    return paths


@pytest.fixture()
def database(app_paths: AppPaths) -> Database:
    db = Database(app_paths.database, app_paths.migrations, app_paths.backups)
    assert db.migrate() == [1, 2, 3, 4, 5]
    db.integrity_check()
    return db


@pytest.fixture()
def fixture_dir() -> Path:
    return ROOT / "tests" / "fixtures"


def insert_invoice(db: Database, identifier: str, code: str, amount_minor: int, currency: str = "CZK", date_text: str = "2026-07-30T10:00:00Z", *, included: int = 1, status: str = "UNMATCHED") -> None:
    now = "2026-07-31T10:00:00Z"
    db.execute(
        "INSERT INTO invoice(external_id,document_uuid,code,document_date_utc,total_minor,currency_code,pay_method,print_format,included,status,raw_json,content_hash,first_seen_utc,last_seen_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
        (identifier, None, code, date_text, amount_minor, currency, 2, 1, included, status, "{}", f"hash-{identifier}", now, now),
    )


def insert_card(db: Database, identifier: str, terminal: str, seq: str, amount_minor: int, currency: str = "CZK", date_text: str = "2026-07-30T10:05:00Z") -> None:
    now = "2026-07-31T10:00:00Z"
    db.execute(
        "INSERT INTO card_transaction(id,terminal_id,seq_id,transaction_type,occurred_at,posted_date,amount_minor,currency_code,authorization_code,masked_card,status,raw_json,content_hash,first_seen_utc,last_seen_utc,row_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
        (identifier, terminal, seq, "Prodej", date_text, date_text[:10], amount_minor, currency, "A001", "****1234", "UNMATCHED", "{}", f"hash-{identifier}", now, now),
    )
