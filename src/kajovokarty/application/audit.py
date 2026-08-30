from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..infrastructure.diagnostics.logging import redact


@dataclass(frozen=True, slots=True)
class AuditContext:
    correlation_id: str
    command_id: str | None = None


class AuditService:
    def __init__(self) -> None:
        seed = f"{platform.node()}|{platform.machine()}|{os.getenv('COMPUTERNAME', '')}"
        self.device_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]

    def append(
        self,
        conn: Any,
        *,
        event_code: str,
        operation_label: str,
        context: AuditContext,
        object_ref: str | None = None,
        before: Any = None,
        after: Any = None,
        redacted_context: dict[str, Any] | None = None,
    ) -> str:
        event_id = uuid4().hex
        conn.execute(
            "INSERT INTO audit_event(event_id,command_id,correlation_id,event_code,operation_label,object_ref,before_json,after_json,windows_user,device_id,created_at_utc,local_time_zone,redacted_context_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                context.command_id,
                context.correlation_id,
                event_code,
                operation_label,
                object_ref,
                None if before is None else json.dumps(redact(before), ensure_ascii=False, sort_keys=True, default=str),
                None if after is None else json.dumps(redact(after), ensure_ascii=False, sort_keys=True, default=str),
                getpass.getuser(),
                self.device_id,
                datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "Europe/Prague",
                json.dumps(redact(redacted_context or {}), ensure_ascii=False, sort_keys=True, default=str),
            ),
        )
        return event_id
