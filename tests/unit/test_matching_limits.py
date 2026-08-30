from __future__ import annotations

from datetime import date

import pytest

from kajovokarty.domain.entities import MatchItem
from kajovokarty.domain.enums import ObjectSide
from kajovokarty.domain.matching import MatchingCancelled, MatchingSearchLimit, MatchingSettings, ReconciliationEngine


def _item(identifier: str, side: ObjectSide, amount: int) -> MatchItem:
    kind = "INVOICE" if side == ObjectSide.DOCUMENT else "CARD"
    return MatchItem(kind, identifier, side, amount, amount, "CZK", date(2026, 7, 30))


def test_matching_can_be_cancelled_before_any_candidate_is_committed() -> None:
    engine = ReconciliationEngine(MatchingSettings())
    with pytest.raises(MatchingCancelled):
        engine.generate(
            [_item("i1", ObjectSide.DOCUMENT, 100), _item("c1", ObjectSide.SOURCE, 100)],
            cancel=lambda: True,
        )


def test_combination_limit_fails_safely_without_partial_result() -> None:
    engine = ReconciliationEngine(MatchingSettings(max_combination=6, max_examined_combinations=100))
    items = [
        *[_item(f"i{index}", ObjectSide.DOCUMENT, 100) for index in range(1, 9)],
        *[_item(f"c{index}", ObjectSide.SOURCE, 100) for index in range(1, 9)],
    ]
    with pytest.raises(MatchingSearchLimit, match="bezpečnostního limitu"):
        engine.generate(items)
