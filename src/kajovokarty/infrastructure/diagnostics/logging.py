from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = re.compile(r"(?i)(access.?token|client.?token|authorization|password|secret)")
_CARD_PATTERN = re.compile(r"(?<!\d)(\d{6})(\d{3,9})(\d{4})(?!\d)")
_EMAIL_PATTERN = re.compile(r"([\w.+-]+)@([\w.-]+)")
_TOKEN_PATTERNS = (
    re.compile(r"(?i)(x-access-token|x-client-token|access[_ -]?token|client[_ -]?token|authorization)\s*[:=]\s*[^,;\s\"}]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\beyJ[A-Za-z0-9._-]{20,}\b"),
    re.compile(r"\bbh_[A-Za-z0-9._-]{20,}\b"),
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "***" if _SENSITIVE_KEYS.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        text = _CARD_PATTERN.sub(lambda m: m.group(1) + "*" * len(m.group(2)) + m.group(3), value)
        text = _EMAIL_PATTERN.sub("***@***", text)
        for pattern in _TOKEN_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text
    return value


class LineRotatingJsonHandler(logging.Handler):
    def __init__(self, directory: Path, *, max_lines: int = 5000, retention_files: int = 14) -> None:
        super().__init__()
        self.directory = directory
        self.max_lines = max_lines
        self.retention_files = retention_files
        self._lock = threading.RLock()
        self._stream: Any = None
        self._line_count = 0
        self._index = 0
        self.directory.mkdir(parents=True, exist_ok=True)
        self._open_current()

    def _open_current(self) -> None:
        day = datetime.now(UTC).strftime("%Y%m%d")
        candidates = sorted(self.directory.glob(f"kajovokarty-{day}-*.jsonl"))
        if candidates:
            last = candidates[-1]
            try:
                self._index = int(last.stem.rsplit("-", 1)[1])
            except ValueError:
                self._index = 0
            self._line_count = _count_lines(last)
            if self._line_count < self.max_lines:
                self._stream = last.open("a", encoding="utf-8", buffering=1)
                return
            self._index += 1
        path = self.directory / f"kajovokarty-{day}-{self._index:03d}.jsonl"
        self._stream = path.open("a", encoding="utf-8", buffering=1)
        self._line_count = _count_lines(path)
        self._cleanup()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = {
                "timestamp_utc": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "level": record.levelname,
                "module": record.name,
                "event_code": getattr(record, "event_code", record.msg if isinstance(record.msg, str) else "log"),
                "message": redact(record.getMessage()),
                "correlation_id": getattr(record, "correlation_id", None),
                "run_id": getattr(record, "run_id", None),
                "command_id": getattr(record, "command_id", None),
                "object_ref": getattr(record, "object_ref", None),
                "duration_ms": getattr(record, "duration_ms", None),
                "counts": redact(getattr(record, "counts", None)),
                "retry_no": getattr(record, "retry_no", None),
                "context": redact(getattr(record, "context", None)),
            }
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
            with self._lock:
                if self._line_count >= self.max_lines:
                    self._stream.close()
                    self._index += 1
                    self._open_current()
                self._stream.write(line + "\n")
                self._line_count += 1
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        super().close()

    def _cleanup(self) -> None:
        files = sorted(self.directory.glob("kajovokarty-*.jsonl"), key=lambda path: path.stat().st_mtime)
        for path in files[:-self.retention_files]:
            path.unlink(missing_ok=True)


def configure_logging(directory: Path, *, max_lines: int = 5000, retention_files: int = 14) -> logging.Logger:
    logger = logging.getLogger("kajovokarty")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    logger.addHandler(LineRotatingJsonHandler(directory, max_lines=max_lines, retention_files=retention_files))
    return logger


def log_event(logger: logging.Logger, level: int, event_code: str, message: str, **context: Any) -> None:
    extra = {"event_code": event_code}
    for key in ("correlation_id", "run_id", "command_id", "object_ref", "duration_ms", "counts", "retry_no"):
        if key in context:
            extra[key] = context.pop(key)
    extra["context"] = redact(context)
    logger.log(level, message, extra=extra)


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as handle:
        return sum(1 for _ in handle)
