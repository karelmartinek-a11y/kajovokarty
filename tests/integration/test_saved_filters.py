from __future__ import annotations

import pytest

from kajovokarty.application.audit import AuditService
from kajovokarty.application.saved_filters import SavedFilterError, SavedFilterService


def test_saved_filter_crud_is_atomic_and_audited(database):
    service = SavedFilterService(database, AuditService())
    created = service.save("search", "Moje platby", {"query": "6689102875", "currency": "EUR"})
    assert service.list("search")[0].values["query"] == "6689102875"

    updated = service.save("search", "Moje platby", {"query": "SEQ-001"})
    assert updated.id == created.id
    assert service.list("search")[0].values == {"query": "SEQ-001"}

    service.remove(created.id)
    assert service.list("search") == []
    events = database.query(
        "SELECT event_code FROM audit_event WHERE object_ref=? ORDER BY created_at_utc",
        (f"SAVED_FILTER:{created.id}",),
    )
    assert [row["event_code"] for row in events] == [
        "SAVED_FILTER_STORED",
        "SAVED_FILTER_STORED",
        "SAVED_FILTER_REMOVED",
    ]


def test_saved_filter_rejects_blank_name(database):
    service = SavedFilterService(database, AuditService())
    with pytest.raises(SavedFilterError):
        service.save("search", "   ", {})
