from __future__ import annotations

from kajovokarty.application.counterparts import CounterpartSearchService
from conftest import insert_card, insert_invoice


def test_counterpart_search_is_currency_sign_and_window_safe(database):
    insert_invoice(database, "inv", "FA1", 10000, "EUR", "2026-07-01T00:00:00Z")
    database.execute("UPDATE invoice SET paid_at_utc=? WHERE external_id=?", ("2026-07-01T00:00:00Z", "inv"))
    insert_card(database, "card-ok", "T", "0001", 10000, "EUR", "2026-07-02T00:00:00Z")
    insert_card(database, "card-czk", "T", "0002", 10000, "CZK", "2026-07-02T00:00:00Z")
    insert_card(database, "card-far", "T", "0003", 10000, "EUR", "2026-08-20T00:00:00Z")
    service = CounterpartSearchService(database)
    seven = service.search("INVOICE", "inv", window_days=7)
    assert [item.object_id for item in seven] == ["card-ok"]
    assert seven[0].score == 90
    all_history = service.search("INVOICE", "inv", window_days=None)
    assert {item.object_id for item in all_history} == {"card-ok", "card-far"}


def test_counterpart_search_never_commits(database):
    service = CounterpartSearchService(database)
    before = database.query("SELECT COUNT(*) AS c FROM match_group")[0]["c"]
    try:
        service.search("INVOICE", "missing")
    except ValueError:
        pass
    after = database.query("SELECT COUNT(*) AS c FROM match_group")[0]["c"]
    assert before == after == 0
