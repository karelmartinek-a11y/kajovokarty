from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Final

CURRENCY_EXPONENTS: Final[dict[str, int]] = {"CZK": 2, "EUR": 2}
_CURRENCY_SYMBOLS: Final[dict[str, str]] = {"CZK": "Kč", "EUR": "€"}


class MoneyError(ValueError):
    """Raised when a monetary operation violates currency or parsing rules."""


def normalize_currency(value: str) -> str:
    code = value.strip().upper()
    aliases = {"KČ": "CZK", "KC": "CZK", "€": "EUR", "EUR": "EUR", "CZK": "CZK"}
    normalized = aliases.get(code, code)
    if normalized not in CURRENCY_EXPONENTS:
        raise MoneyError(f"Nepodporovaná měna: {value!r}")
    return normalized


def parse_decimal(value: object) -> Decimal:
    """Parse a human/Excel amount without ever converting through float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Excel libraries can expose numeric cells as float. String conversion preserves the
        # decimal representation emitted by the library and avoids binary arithmetic here.
        value = format(value, ".15g")
    if value is None:
        raise MoneyError("Částka chybí.")
    text = str(value).strip().replace("\u00a0", " ")
    if not text:
        raise MoneyError("Částka chybí.")
    negative_parentheses = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = re.sub(r"(?i)\b(CZK|EUR|KČ|KC)\b|€", "", text).strip()
    text = text.replace(" ", "").replace("'", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise MoneyError(f"Neplatná částka: {value!r}") from exc
    return -parsed if negative_parentheses else parsed


def to_minor(value: object, currency: str) -> int:
    code = normalize_currency(currency)
    exponent = CURRENCY_EXPONENTS[code]
    quant = Decimal(1).scaleb(-exponent)
    decimal_value = parse_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)
    return int(decimal_value.scaleb(exponent))


def from_minor(amount_minor: int, currency: str) -> Decimal:
    code = normalize_currency(currency)
    exponent = CURRENCY_EXPONENTS[code]
    return Decimal(amount_minor).scaleb(-exponent)


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise MoneyError("amount_minor musí být celé číslo.")

    @classmethod
    def parse(cls, value: object, currency: str) -> Money:
        return cls(to_minor(value, currency), currency)

    @property
    def decimal(self) -> Decimal:
        return from_minor(self.amount_minor, self.currency)

    def _check(self, other: Money) -> None:
        if self.currency != other.currency:
            raise MoneyError(f"Nelze kombinovat {self.currency} a {other.currency}.")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount_minor, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount_minor), self.currency)

    def format(self) -> str:
        value = f"{self.decimal:,.2f}".replace(",", "\u00a0").replace(".", ",")
        return f"{value} {_CURRENCY_SYMBOLS.get(self.currency, self.currency)}"
