"""Small, explicit domain objects for locally imported financial movements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class MovementType(StrEnum):
    """The economic kind of a movement, independent from its signed amount."""

    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"
    PENDING = "pending"


class Person(StrEnum):
    """Person selected by the user for the imported account or statement."""

    SELF = "self"
    SPOUSE = "spouse"
    SHARED = "shared"


class SourceKind(StrEnum):
    BANK_ACCOUNT = "bank_account"
    CREDIT_CARD = "credit_card"


@dataclass(frozen=True, slots=True)
class Money:
    """An exact monetary value stored as integer minor units, currently BRL cents."""

    minor_units: int
    currency: str = "BRL"

    def __post_init__(self) -> None:
        if isinstance(self.minor_units, bool) or not isinstance(self.minor_units, int):
            raise TypeError("minor_units must be an integer; binary floating-point is not allowed")
        if self.currency != "BRL":
            raise ValueError("only BRL is supported in this version")

    @classmethod
    def from_decimal(cls, value: Decimal) -> Money:
        """Convert a Decimal only when it is exactly representable in cents."""
        if not isinstance(value, Decimal):
            raise TypeError("money must be created from Decimal, never float or another type")
        if not value.is_finite():
            raise ValueError("monetary amount must be finite")

        try:
            scaled = value * Decimal(100)
            integral = scaled.to_integral_value()
        except InvalidOperation as error:
            raise ValueError("monetary amount is outside the supported numeric range") from error

        if scaled != integral:
            raise ValueError("monetary amount must have no more than two decimal places")
        return cls(int(integral))

    def to_decimal(self) -> Decimal:
        """Return an exact Decimal representation; never use this for binary floats."""
        return Decimal(self.minor_units).scaleb(-2)


@dataclass(frozen=True, slots=True)
class Category:
    """A macro/micro category pair from the user's historical workbook."""

    macro: str
    micro: str

    def __post_init__(self) -> None:
        if not self.macro.strip() or not self.micro.strip():
            raise ValueError("macro and micro categories must not be empty")


@dataclass(frozen=True, slots=True)
class Transaction:
    """A normalized movement with separate occurrence and posting dates."""

    transaction_id: str
    description: str
    amount: Money
    movement_type: MovementType
    person: Person
    occurred_on: date
    posted_on: date | None = None
    category: Category | None = None
    source_key: str = "unassigned"
    source_kind: SourceKind = SourceKind.BANK_ACCOUNT

    def __post_init__(self) -> None:
        if not self.transaction_id.strip():
            raise ValueError("transaction_id must not be empty")
        if not self.description.strip():
            raise ValueError("description must not be empty")
        if not self.source_key.strip():
            raise ValueError("source_key must not be empty")
        if not isinstance(self.amount, Money):
            raise TypeError("amount must be Money")
        if self.movement_type is not MovementType.EXPENSE and self.category is not None:
            raise ValueError("only an expense may have an expense category")
