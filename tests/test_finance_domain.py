from datetime import date
from decimal import Decimal

import pytest

from streamline_finance.categorization import (
    CategorizationRule,
    CategorizationStatus,
    suggest_category,
)
from streamline_finance.domain import (
    Category,
    Money,
    MovementType,
    Person,
    Transaction,
)


def test_money_keeps_exact_brl_minor_units_for_positive_and_negative_values() -> None:
    positive = Money.from_decimal(Decimal("1234.56"))
    negative = Money.from_decimal(Decimal("-12.34"))

    assert positive.minor_units == 123456
    assert positive.to_decimal() == Decimal("1234.56")
    assert negative.minor_units == -1234
    assert negative.to_decimal() == Decimal("-12.34")
    assert positive.currency == "BRL"


@pytest.mark.parametrize("value", [Decimal("1.001"), Decimal("NaN"), Decimal("Infinity")])
def test_money_rejects_values_that_cannot_be_represented_as_exact_cents(value: Decimal) -> None:
    with pytest.raises(ValueError):
        Money.from_decimal(value)


def test_money_rejects_float_instead_of_silently_accepting_binary_precision() -> None:
    with pytest.raises(TypeError):
        Money.from_decimal(0.1)


def test_transaction_preserves_purchase_and_posting_dates_and_owner() -> None:
    transaction = Transaction(
        transaction_id="synthetic-001",
        description="COMPRA FICTICIA",
        amount=Money.from_decimal(Decimal("-12.34")),
        movement_type=MovementType.EXPENSE,
        person=Person.SELF,
        occurred_on=date(2026, 2, 3),
        posted_on=date(2026, 2, 4),
    )

    assert transaction.occurred_on == date(2026, 2, 3)
    assert transaction.posted_on == date(2026, 2, 4)
    assert transaction.person is Person.SELF
    assert transaction.movement_type is MovementType.EXPENSE


def test_exact_description_rule_suggests_category_case_and_spacing_insensitively() -> None:
    category = Category(macro="Necessidades básicas", micro="Supermercado")
    rules = [CategorizationRule("rule-1", "Mercado Exemplo", category)]
    transaction = make_transaction("  MERCADO   EXEMPLO  ")

    result = suggest_category(transaction, rules)

    assert result.status is CategorizationStatus.SUGGESTED
    assert result.suggested_category == category
    assert result.matched_rule_ids == ("rule-1",)
    assert "rule-1" in result.explanation


def test_unknown_description_requires_review_instead_of_guessing() -> None:
    category = Category(macro="Necessidades básicas", micro="Supermercado")

    result = suggest_category(
        make_transaction("LOJA NUNCA VISTA"),
        [CategorizationRule("rule-1", "Mercado Exemplo", category)],
    )

    assert result.status is CategorizationStatus.NEEDS_REVIEW
    assert result.suggested_category is None
    assert result.matched_rule_ids == ()


def test_conflicting_exact_rules_are_ambiguous_and_return_no_suggestion() -> None:
    first = Category(macro="Necessidades básicas", micro="Supermercado")
    second = Category(macro="Lazer", micro="Restaurantes")
    rules = [
        CategorizationRule("rule-1", "Comercio Exemplo", first),
        CategorizationRule("rule-2", "COMERCIO EXEMPLO", second),
    ]

    result = suggest_category(make_transaction("Comercio Exemplo"), rules)

    assert result.status is CategorizationStatus.AMBIGUOUS
    assert result.suggested_category is None
    assert result.matched_rule_ids == ("rule-1", "rule-2")


@pytest.mark.parametrize("movement_type", [MovementType.INCOME, MovementType.TRANSFER])
def test_non_expense_movement_is_never_auto_categorized(movement_type: MovementType) -> None:
    category = Category(macro="Necessidades básicas", micro="Supermercado")
    rules = [CategorizationRule("rule-1", "Mercado Exemplo", category)]

    result = suggest_category(
        make_transaction("Mercado Exemplo", movement_type=movement_type), rules
    )

    assert result.status is CategorizationStatus.NOT_APPLICABLE
    assert result.suggested_category is None
    assert result.matched_rule_ids == ()


def test_manual_confirmation_keeps_original_suggestion_and_rule_provenance() -> None:
    suggested = Category(macro="Necessidades básicas", micro="Supermercado")
    corrected = Category(macro="Lazer", micro="Restaurantes")
    result = suggest_category(
        make_transaction("Mercado Exemplo"),
        [CategorizationRule("rule-1", "Mercado Exemplo", suggested)],
    )

    confirmed = result.confirm(corrected)

    assert result.confirmed_category is None
    assert confirmed.status is CategorizationStatus.CONFIRMED
    assert confirmed.suggested_category == suggested
    assert confirmed.confirmed_category == corrected
    assert confirmed.matched_rule_ids == ("rule-1",)


def test_non_expense_result_cannot_be_manually_categorized_as_expense() -> None:
    result = suggest_category(
        make_transaction("Transferencia Ficticia", movement_type=MovementType.TRANSFER), []
    )

    with pytest.raises(ValueError):
        result.confirm(Category(macro="Lazer", micro="Restaurantes"))


def make_transaction(
    description: str,
    *,
    movement_type: MovementType = MovementType.EXPENSE,
) -> Transaction:
    return Transaction(
        transaction_id="synthetic-test-id",
        description=description,
        amount=Money.from_decimal(Decimal("-10.00")),
        movement_type=movement_type,
        person=Person.SELF,
        occurred_on=date(2026, 2, 3),
    )
