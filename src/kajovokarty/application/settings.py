from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import uuid4

from ..app.config import SETTING_SPECS, SettingSpec
from ..infrastructure.importers.common import utc_now
from ..infrastructure.persistence.database import Database
from .audit import AuditContext, AuditService


class SettingsValidationError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("Některá nastavení nejsou platná.")
        self.errors = errors


class SettingsService:
    def __init__(self, database: Database, audit: AuditService) -> None:
        self.database = database
        self.audit = audit

    def all(self) -> dict[str, Any]:
        values = {key: spec.default for key, spec in SETTING_SPECS.items()}
        for row in self.database.query("SELECT key,typed_value,value_type FROM app_setting"):
            values[row["key"]] = self._decode(row["typed_value"], row["value_type"])
        return values

    def get(self, key: str) -> Any:
        if key not in SETTING_SPECS:
            raise KeyError(key)
        row = self.database.query("SELECT typed_value,value_type FROM app_setting WHERE key=?", (key,))
        return SETTING_SPECS[key].default if not row else self._decode(row[0]["typed_value"], row[0]["value_type"])

    def validate(self, values: dict[str, Any]) -> dict[str, Any]:
        errors: dict[str, str] = {}
        normalized: dict[str, Any] = {}
        for key, value in values.items():
            spec = SETTING_SPECS.get(key)
            if spec is None:
                errors[key] = "Neznámé nastavení."
                continue
            try:
                normalized[key] = self._validate_one(spec, value)
            except (TypeError, ValueError) as exc:
                errors[key] = str(exc)
        if errors:
            raise SettingsValidationError(errors)
        return normalized

    def save(self, values: dict[str, Any], *, correlation_id: str | None = None) -> None:
        normalized = self.validate(values)
        correlation = correlation_id or uuid4().hex
        with self.database.transaction() as conn:
            for key, value in normalized.items():
                before_row = conn.execute("SELECT typed_value,value_type FROM app_setting WHERE key=?", (key,)).fetchone()
                before = None if before_row is None else self._decode(before_row["typed_value"], before_row["value_type"])
                encoded, value_type = self._encode(value)
                conn.execute(
                    "INSERT INTO app_setting(key,typed_value,value_type,updated_at_utc) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET typed_value=excluded.typed_value,value_type=excluded.value_type,updated_at_utc=excluded.updated_at_utc",
                    (key, encoded, value_type, utc_now()),
                )
                self.audit.append(
                    conn,
                    event_code="SETTING_CHANGED",
                    operation_label=f"Změna nastavení: {SETTING_SPECS[key].label}",
                    context=AuditContext(correlation),
                    object_ref=f"SETTING:{key}",
                    before=before,
                    after=value,
                )

    @staticmethod
    def _validate_one(spec: SettingSpec, value: Any) -> Any:
        expected = type(spec.default)
        if expected is bool:
            if isinstance(value, bool):
                normalized = value
            elif str(value).casefold() in {"1", "true", "ano"}:
                normalized = True
            elif str(value).casefold() in {"0", "false", "ne"}:
                normalized = False
            else:
                raise ValueError("Zadejte Ano nebo Ne.")
        elif expected is int:
            if isinstance(value, bool):
                raise ValueError("Zadejte celé číslo.")
            normalized = int(value)
        elif expected is float:
            normalized = float(str(value).replace(",", "."))
        elif isinstance(spec.default, date):
            normalized = value if isinstance(value, date) else date.fromisoformat(str(value))
        elif isinstance(spec.default, (list, dict)):
            normalized = value
            if not isinstance(value, expected):
                raise ValueError("Nesprávný typ hodnoty.")
        else:
            normalized = str(value)
        if isinstance(normalized, (int, float)):
            if spec.minimum is not None and normalized < spec.minimum:
                raise ValueError(f"Minimum je {spec.minimum}.")
            if spec.maximum is not None and normalized > spec.maximum:
                raise ValueError(f"Maximum je {spec.maximum}.")
        if spec.choices and normalized not in spec.choices:
            raise ValueError("Zvolte jednu z nabízených hodnot.")
        return normalized

    @staticmethod
    def _encode(value: Any) -> tuple[str, str]:
        if isinstance(value, bool):
            return ("true" if value else "false"), "bool"
        if isinstance(value, int):
            return str(value), "int"
        if isinstance(value, float):
            return repr(value), "float"
        if isinstance(value, date):
            return value.isoformat(), "date"
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True), "json"
        return str(value), "str"

    @staticmethod
    def _decode(value: str, value_type: str) -> Any:
        if value_type == "bool":
            return value == "true"
        if value_type == "int":
            return int(value)
        if value_type == "float":
            return float(value)
        if value_type == "date":
            return date.fromisoformat(value)
        if value_type == "json":
            return json.loads(value)
        return value
