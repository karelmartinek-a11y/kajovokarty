from __future__ import annotations

import json
from typing import Any

from ..infrastructure.importers.common import canonical_json, utc_now
from ..infrastructure.persistence.database import Database


class ViewStateService:
    """Persistence boundary for local, non-authoritative UI state.

    UI widgets never write SQLite directly. Corrupt or obsolete state is ignored so a
    damaged layout can never prevent the application from opening.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def load(self, view_key: str, default: Any = None) -> Any:
        rows = self.database.query("SELECT state_json FROM user_view_state WHERE view_key=?", (view_key,))
        if not rows:
            return default
        try:
            return json.loads(str(rows[0]["state_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return default

    def save(self, view_key: str, state: Any) -> None:
        payload = canonical_json(state)
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO user_view_state(view_key,state_json,updated_at_utc) VALUES(?,?,?) "
                "ON CONFLICT(view_key) DO UPDATE SET state_json=excluded.state_json,updated_at_utc=excluded.updated_at_utc",
                (view_key, payload, utc_now()),
            )

    def remove(self, view_key: str) -> None:
        with self.database.transaction() as conn:
            conn.execute("DELETE FROM user_view_state WHERE view_key=?", (view_key,))
