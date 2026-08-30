from kajovokarty.application.view_state import ViewStateService


def test_view_state_roundtrip_and_corrupt_fallback(database) -> None:
    service = ViewStateService(database)
    state = {"splitter": [420, 610, 430], "columns": {"invoice": "abc"}}
    service.save("matching", state)
    assert service.load("matching") == state

    with database.transaction() as conn:
        conn.execute(
            "UPDATE user_view_state SET state_json='not-json' WHERE view_key='matching'"
        )
    assert service.load("matching", {"safe": True}) == {"safe": True}

    service.remove("matching")
    assert service.load("matching", None) is None
