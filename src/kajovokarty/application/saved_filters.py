from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ..infrastructure.importers.common import canonical_json, utc_now
from ..infrastructure.persistence.database import Database
from .audit import AuditContext, AuditService


class SavedFilterError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SavedFilter:
    id: str
    name: str
    view_key: str
    values: dict[str, Any]
    created_at_utc: str
    updated_at_utc: str


class SavedFilterService:
    """Atomic, audited storage for reusable human-named filters."""

    def __init__(self, database: Database, audit: AuditService) -> None:
        self.database = database
        self.audit = audit

    def list(self, view_key: str) -> list[SavedFilter]:
        rows = self.database.query(
            "SELECT id,name,view_key,filter_json,created_at_utc,updated_at_utc "
            "FROM saved_filter WHERE view_key=? ORDER BY name COLLATE NOCASE",
            (view_key,),
        )
        result: list[SavedFilter] = []
        for row in rows:
            try:
                values = json.loads(row["filter_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                values = {}
            if not isinstance(values, dict):
                values = {}
            result.append(
                SavedFilter(
                    id=str(row["id"]),
                    name=str(row["name"]),
                    view_key=str(row["view_key"]),
                    values=values,
                    created_at_utc=str(row["created_at_utc"]),
                    updated_at_utc=str(row["updated_at_utc"]),
                )
            )
        return result

    def save(self, view_key: str, name: str, values: dict[str, Any]) -> SavedFilter:
        clean_view = view_key.strip()
        clean_name = " ".join(name.split())
        if not clean_view:
            raise SavedFilterError("Chybí identifikátor pohledu.")
        if not clean_name:
            raise SavedFilterError("Zadejte lidský název filtru.")
        if len(clean_name) > 120:
            raise SavedFilterError("Název filtru může mít nejvýše 120 znaků.")
        encoded = canonical_json(values)
        now = utc_now()
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            previous = conn.execute(
                "SELECT id,filter_json,created_at_utc FROM saved_filter WHERE name=?",
                (clean_name,),
            ).fetchone()
            filter_id = str(previous["id"]) if previous is not None else uuid4().hex
            created = str(previous["created_at_utc"]) if previous is not None else now
            conn.execute(
                "INSERT INTO saved_filter(id,name,view_key,filter_json,created_at_utc,updated_at_utc) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                "view_key=excluded.view_key,filter_json=excluded.filter_json,updated_at_utc=excluded.updated_at_utc",
                (filter_id, clean_name, clean_view, encoded, created, now),
            )
            self.audit.append(
                conn,
                event_code="SAVED_FILTER_STORED",
                operation_label="Uložit filtr",
                context=AuditContext(correlation),
                object_ref=f"SAVED_FILTER:{filter_id}",
                before=None if previous is None else {"filter_json": previous["filter_json"]},
                after={"name": clean_name, "view_key": clean_view, "values": values},
            )
        return SavedFilter(filter_id, clean_name, clean_view, dict(values), created, now)

    def remove(self, filter_id: str) -> None:
        correlation = uuid4().hex
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM saved_filter WHERE id=?", (filter_id,)).fetchone()
            if row is None:
                raise SavedFilterError("Uložený filtr už neexistuje.")
            conn.execute("DELETE FROM saved_filter WHERE id=?", (filter_id,))
            self.audit.append(
                conn,
                event_code="SAVED_FILTER_REMOVED",
                operation_label="Odstranit uložený filtr",
                context=AuditContext(correlation),
                object_ref=f"SAVED_FILTER:{filter_id}",
                before={"name": row["name"], "view_key": row["view_key"], "filter_json": row["filter_json"]},
                after=None,
            )
