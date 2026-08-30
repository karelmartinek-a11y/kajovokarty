from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Callable
from uuid import uuid4

from ..infrastructure.importers.common import utc_now
from ..infrastructure.persistence.database import Database


class OperationState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    DISCARDED = "DISCARDED"


@dataclass(slots=True)
class CancellationToken:
    _event: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(slots=True)
class OperationSnapshot:
    id: str
    correlation_id: str
    operation_type: str
    state: OperationState
    step: str
    current: int | float | None
    total: int | float | None
    message: str
    heartbeat_utc: str
    error: str | None = None
    recovery: dict[str, Any] = field(default_factory=dict)


class OperationContext:
    def __init__(self, manager: OperationManager, operation_id: str, token: CancellationToken) -> None:
        self.manager = manager
        self.operation_id = operation_id
        self.token = token

    def progress(self, current: int | float, total: int | float, message: str, step: str = "Pracuji") -> None:
        self.manager._update(self.operation_id, step=step, current=current, total=total, message=message)

    def heartbeat(self, message: str | None = None) -> None:
        """Refresh liveness without replacing the user-facing progress message."""
        if message is None:
            self.manager._update(self.operation_id)
        else:
            self.manager._update(self.operation_id, message=message)

    def is_cancelled(self) -> bool:
        return self.token.is_cancelled()


OperationCallable = Callable[[OperationContext], Any]
Listener = Callable[[OperationSnapshot], None]


class OperationManager:
    def __init__(self, database: Database, max_workers: int = 2) -> None:
        self.database = database
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="kajovokarty-worker")
        self._lock = threading.RLock()
        self._operations: dict[str, OperationSnapshot] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._listeners: list[Listener] = []
        self._main_source_lock = threading.Lock()
        self._mark_interrupted()

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def submit(
        self,
        operation_type: str,
        function: OperationCallable,
        *,
        exclusive_sources: bool = False,
        recovery: dict[str, Any] | None = None,
    ) -> str:
        operation_id = uuid4().hex
        correlation_id = uuid4().hex
        token = CancellationToken()
        snapshot = OperationSnapshot(
            operation_id,
            correlation_id,
            operation_type,
            OperationState.QUEUED,
            "Ve frontě",
            0,
            None,
            "Čeká na spuštění",
            utc_now(),
            recovery=dict(recovery or {}),
        )
        with self._lock:
            self._operations[operation_id] = snapshot
            self._tokens[operation_id] = token
        self._persist(snapshot)
        future = self.executor.submit(self._run, operation_id, function, exclusive_sources)
        self._futures[operation_id] = future
        return operation_id

    def cancel(self, operation_id: str) -> None:
        with self._lock:
            token = self._tokens.get(operation_id)
            snapshot = self._operations.get(operation_id)
            if token is None or snapshot is None or snapshot.state not in {OperationState.QUEUED, OperationState.RUNNING}:
                return
            token.cancel()
            snapshot.state = OperationState.CANCELLING
            snapshot.message = "Probíhá bezpečné zrušení…"
            snapshot.heartbeat_utc = utc_now()
            self._persist(snapshot)
            self._notify(snapshot)

    def snapshot(self, operation_id: str) -> OperationSnapshot | None:
        with self._lock:
            current = self._operations.get(operation_id)
            return None if current is None else replace(current)

    def snapshots(self) -> list[OperationSnapshot]:
        with self._lock:
            return [replace(snapshot) for snapshot in self._operations.values()]

    def interrupted(self) -> list[OperationSnapshot]:
        rows = self.database.query(
            "SELECT * FROM operation_run WHERE state='INTERRUPTED' ORDER BY started_at_utc"
        )
        return [self._snapshot_from_row(row) for row in rows]

    def discard_interrupted(self, operation_id: str) -> None:
        changed = self.database.execute(
            "UPDATE operation_run SET state='DISCARDED',step='Zahozeno',"
            "message='Uživatel přerušený běh vědomě zahodil.',finished_at_utc=? "
            "WHERE id=? AND state='INTERRUPTED'",
            (utc_now(), operation_id),
        )
        if changed != 1:
            raise ValueError("Přerušený běh už není dostupný k zahození.")

    def shutdown(self, *, cancel: bool = False) -> None:
        if cancel:
            for operation_id in list(self._tokens):
                self.cancel(operation_id)
        self.executor.shutdown(wait=True, cancel_futures=False)

    def _run(self, operation_id: str, function: OperationCallable, exclusive_sources: bool) -> None:
        token = self._tokens[operation_id]
        lock = self._main_source_lock if exclusive_sources else _NoopLock()
        acquired = lock.acquire(blocking=False) if exclusive_sources else True
        if not acquired:
            self._finish(operation_id, OperationState.FAILED, "Jiný hlavní běh už pracuje se stejnými zdroji.")
            return
        try:
            self._update(operation_id, state=OperationState.RUNNING, step="Spuštěno", message="Operace byla spuštěna")
            context = OperationContext(self, operation_id, token)
            if token.is_cancelled():
                self._finish(operation_id, OperationState.CANCELLED, "Operace byla bezpečně zrušena před spuštěním.")
                return
            function(context)
            if token.is_cancelled():
                self._finish(operation_id, OperationState.CANCELLED, "Operace byla bezpečně zrušena.")
            else:
                self._finish(operation_id, OperationState.SUCCEEDED, "Operace byla úspěšně dokončena.")
        except Exception as exc:
            if token.is_cancelled():
                self._finish(operation_id, OperationState.CANCELLED, "Operace byla bezpečně zrušena.")
            else:
                self._finish(operation_id, OperationState.FAILED, f"{type(exc).__name__}: {exc}")
        finally:
            if exclusive_sources:
                lock.release()

    def _update(self, operation_id: str, **changes: Any) -> None:
        with self._lock:
            snapshot = self._operations[operation_id]
            for key, value in changes.items():
                setattr(snapshot, key, value)
            snapshot.heartbeat_utc = utc_now()
            self._persist(snapshot)
            self._notify(snapshot)

    def _finish(self, operation_id: str, state: OperationState, message: str) -> None:
        with self._lock:
            snapshot = self._operations[operation_id]
            snapshot.state = state
            snapshot.message = message
            snapshot.error = message if state == OperationState.FAILED else None
            snapshot.heartbeat_utc = utc_now()
            self._persist(snapshot, finished=True)
            self._notify(snapshot)

    def _persist(self, snapshot: OperationSnapshot, *, finished: bool = False) -> None:
        error_json = None if snapshot.error is None else json.dumps({"message": snapshot.error}, ensure_ascii=False)
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO operation_run(id,correlation_id,operation_type,state,step,current_count,total_count,message,heartbeat_at_utc,started_at_utc,finished_at_utc,error_json,recovery_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET state=excluded.state,step=excluded.step,current_count=excluded.current_count,total_count=excluded.total_count,message=excluded.message,heartbeat_at_utc=excluded.heartbeat_at_utc,finished_at_utc=excluded.finished_at_utc,error_json=excluded.error_json,recovery_json=excluded.recovery_json",
                (
                    snapshot.id,
                    snapshot.correlation_id,
                    snapshot.operation_type,
                    snapshot.state.value,
                    snapshot.step,
                    snapshot.current,
                    snapshot.total,
                    snapshot.message,
                    snapshot.heartbeat_utc,
                    snapshot.heartbeat_utc,
                    snapshot.heartbeat_utc if finished else None,
                    error_json,
                    json.dumps(snapshot.recovery, ensure_ascii=False, sort_keys=True),
                ),
            )

    def _notify(self, snapshot: OperationSnapshot) -> None:
        copy = replace(snapshot)
        for listener in tuple(self._listeners):
            listener(copy)

    def _mark_interrupted(self) -> None:
        if not self.database.path.exists():
            return
        try:
            self.database.execute(
                "UPDATE operation_run SET state='INTERRUPTED',step='Přerušeno',"
                "message='Běh byl přerušen pádem nebo restartem aplikace.',finished_at_utc=? "
                "WHERE state IN ('QUEUED','RUNNING','CANCELLING')",
                (utc_now(),),
            )
            for row in self.database.query(
                "SELECT * FROM operation_run WHERE state='INTERRUPTED' ORDER BY started_at_utc"
            ):
                snapshot = self._snapshot_from_row(row)
                self._operations[snapshot.id] = snapshot
        except Exception:
            return

    @staticmethod
    def _snapshot_from_row(row: Any) -> OperationSnapshot:
        try:
            recovery = json.loads(row["recovery_json"] or "{}")
        except (TypeError, ValueError, KeyError):
            recovery = {}
        try:
            error = json.loads(row["error_json"] or "{}").get("message")
        except (TypeError, ValueError, AttributeError, KeyError):
            error = None
        return OperationSnapshot(
            id=str(row["id"]),
            correlation_id=str(row["correlation_id"]),
            operation_type=str(row["operation_type"]),
            state=OperationState(str(row["state"])),
            step=str(row["step"]),
            current=row["current_count"],
            total=row["total_count"],
            message=str(row["message"]),
            heartbeat_utc=str(row["heartbeat_at_utc"]),
            error=error,
            recovery=recovery if isinstance(recovery, dict) else {},
        )


class _NoopLock:
    def acquire(self, blocking: bool = True) -> bool:
        return True

    def release(self) -> None:
        return None
