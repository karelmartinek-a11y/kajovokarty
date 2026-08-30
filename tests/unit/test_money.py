from decimal import Decimal

import pytest

from kajovokarty.domain.money import Money, MoneyError, from_minor, parse_decimal, to_minor


def test_money_parsing_and_round_half_up() -> None:
    assert parse_decimal("1 234,565 CZK") == Decimal("1234.565")
    assert to_minor("1 234,565", "CZK") == 123457
    assert to_minor("(10,00)", "EUR") == -1000
    assert from_minor(521070, "EUR") == Decimal("5210.70")


def test_money_never_combines_currencies() -> None:
    with pytest.raises(MoneyError):
        _ = Money(100, "CZK") + Money(100, "EUR")


def test_money_format_keeps_sign_and_currency() -> None:
    assert Money(-12345, "CZK").format() == "-123,45 Kč"
    assert Money(191695, "EUR").format() == "1\u00a0916,95 €"
