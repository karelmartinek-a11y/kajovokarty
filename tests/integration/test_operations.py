from __future__ import annotations

import threading
import time

from kajovokarty.application.operations import OperationManager, OperationState
from kajovokarty.infrastructure.persistence.database import Database


def test_cancelled_queued_operation_does_not_execute(database: Database) -> None:
    manager = OperationManager(database, max_workers=1)
    blocker = threading.Event()
    executed = threading.Event()

    def first(context) -> None:
        blocker.wait(timeout=2)

    def second(context) -> None:
        executed.set()

    first_id = manager.submit("FIRST", first)
    second_id = manager.submit("SECOND", second)
    manager.cancel(second_id)
    blocker.set()
    deadline = time.time() + 3
    while time.time() < deadline:
        snapshot = manager.snapshot(second_id)
        if snapshot and snapshot.state in {OperationState.CANCELLED, OperationState.SUCCEEDED, OperationState.FAILED}:
            break
        time.sleep(0.01)
    manager.shutdown()
    assert not executed.is_set()
    assert manager.snapshot(second_id).state == OperationState.CANCELLED
    assert database.scalar("SELECT state FROM operation_run WHERE id=?", (second_id,)) == "CANCELLED"
    assert database.scalar("SELECT state FROM operation_run WHERE id=?", (first_id,)) == "SUCCEEDED"


def test_interrupted_operation_preserves_recovery_and_can_be_discarded(database: Database) -> None:
    now = "2026-07-31T10:00:00Z"
    database.execute(
        "INSERT INTO operation_run(id,correlation_id,operation_type,state,step,current_count,total_count,message,heartbeat_at_utc,started_at_utc,recovery_json) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "old-run",
            "old-correlation",
            "FULL_WORKFLOW",
            "RUNNING",
            "Import",
            1,
            4,
            "Pracuji",
            now,
            now,
            '{"booking_paths":["C:/Data/booking.csv"],"bank_items":[]}',
        ),
    )

    manager = OperationManager(database, max_workers=1)
    interrupted = manager.interrupted()
    assert len(interrupted) == 1
    assert interrupted[0].state == OperationState.INTERRUPTED
    assert interrupted[0].recovery["booking_paths"] == ["C:/Data/booking.csv"]
    assert manager.snapshot("old-run") is not None

    manager.discard_interrupted("old-run")
    assert database.scalar("SELECT state FROM operation_run WHERE id='old-run'") == "DISCARDED"
    assert manager.interrupted() == []
    manager.shutdown()
