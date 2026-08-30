from datetime import date, datetime, UTC

from kajovokarty.domain.entities import MatchItem
from kajovokarty.domain.enums import ObjectSide
from kajovokarty.domain.matching import MatchingSettings, ReconciliationEngine


def item(kind: str, identifier: str, side: ObjectSide, amount: int, *, currency: str = "CZK", day: int = 30, booking: str | None = None, direct: bool = False) -> MatchItem:
    return MatchItem(kind, identifier, side, amount, amount, currency, date(2026, 7, day), booking_reference=booking, paid_at=datetime(2026, 7, day, tzinfo=UTC) if side == ObjectSide.DOCUMENT else None, metadata={"reservation_invoice_link": direct})


def test_exact_card_match_is_deterministic() -> None:
    engine = ReconciliationEngine(MatchingSettings())
    values = [item("INVOICE", "i1", ObjectSide.DOCUMENT, 10000), item("CARD", "CARD:c1", ObjectSide.SOURCE, 10000)]
    first = engine.generate(values)
    second = engine.generate(reversed(values))
    assert [(c.document_ids, c.source_refs, c.score) for c in first] == [(c.document_ids, c.source_refs, c.score) for c in second]
    assert first[0].difference_minor == 0
    assert first[0].can_auto_match


def test_booking_direct_link_reaches_auto_threshold() -> None:
    engine = ReconciliationEngine(MatchingSettings())
    values = [
        item("INVOICE", "FA20265875", ObjectSide.DOCUMENT, 10000, booking="6689102875", direct=True),
        item("BOOKING", "BOOKING:b1", ObjectSide.SOURCE, 10000, booking="6689102875"),
    ]
    candidate = engine.generate(values)[0]
    assert candidate.score == 95
    assert candidate.can_auto_match


def test_equal_combinations_are_not_silently_auto_matched() -> None:
    engine = ReconciliationEngine(MatchingSettings())
    values = [
        item("INVOICE", "i1", ObjectSide.DOCUMENT, 10000),
        item("CARD", "CARD:c1", ObjectSide.SOURCE, 10000),
        item("CARD", "CARD:c2", ObjectSide.SOURCE, 10000),
    ]
    candidates = engine.generate(values)
    exact = [candidate for candidate in candidates if candidate.difference_minor == 0]
    assert len(exact) >= 2
    assert not any(candidate.can_auto_match for candidate in exact)


def test_currency_and_date_are_hard_gates() -> None:
    engine = ReconciliationEngine(MatchingSettings())
    assert engine.generate([item("INVOICE", "i1", ObjectSide.DOCUMENT, 100, currency="CZK"), item("CARD", "CARD:c1", ObjectSide.SOURCE, 100, currency="EUR")]) == []
    assert engine.generate([item("INVOICE", "i1", ObjectSide.DOCUMENT, 100, day=1), item("CARD", "CARD:c1", ObjectSide.SOURCE, 100, day=30)]) == []
