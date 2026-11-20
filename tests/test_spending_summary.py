from datetime import date

from streamline_finance.domain import Category, MovementType, Person, SourceKind
from streamline_finance.storage import StoredTransaction
from streamline_finance.ui_summary import (
    build_spending_summary,
    build_spending_trend,
    category_highlights,
    compare_spending_periods,
    format_brl,
    format_variation_percent,
    top_expenses,
)


def test_monthly_spending_summary_uses_integer_cents_and_only_confirmed_expenses() -> None:
    rows = [
        transaction(
            "expense-1", -1234, MovementType.EXPENSE, "self", "2026-01-03", "Needs", "Food"
        ),
        transaction("expense-2", -500, MovementType.EXPENSE, "self", "2026-01-04", "Needs", "Food"),
        transaction("expense-3", -2500, MovementType.EXPENSE, "spouse", "2026-02-01", None, None),
        transaction("pending", -9000, MovementType.PENDING, "self", "2026-01-10", None, None),
        transaction("income", 50000, MovementType.INCOME, "self", "2026-01-01", None, None),
        transaction("transfer", -10000, MovementType.TRANSFER, "self", "2026-01-12", None, None),
    ]

    summary = build_spending_summary(rows, month="2026-01")

    assert summary.total_minor_units == 1734
    assert summary.transaction_count == 2
    assert summary.by_person == {"self": 1734}
    assert summary.by_category == {("Needs", "Food"): 1734}


def test_invoice_transactions_use_billing_month_for_reports_but_keep_purchase_date():
    installment = transaction(
        "invoice-installment", -2500, MovementType.EXPENSE, "self", "2026-07-10", "Needs", "Food"
    )
    installment = transaction_with_invoice_month(installment, "2026-09")

    summary = build_spending_summary([installment], month="2026-09")
    trend = build_spending_trend(
        [installment],
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        granularity="month",
        dimension="total",
    )
    selected = top_expenses([installment], start=date(2026, 9, 1), end=date(2026, 9, 30))

    assert summary.total_minor_units == 2500
    assert trend[0].period == "2026-09"
    assert selected[0].occurred_on == date(2026, 7, 10)
    assert (
        top_expenses([installment], start=date(2026, 9, 15), end=date(2026, 9, 30))[0].invoice_month
        == "2026-09"
    )
    partial_month = build_spending_trend(
        [installment],
        start=date(2026, 9, 15),
        end=date(2026, 9, 30),
        granularity="month",
        dimension="total",
    )
    assert partial_month[0].amount_minor_units == 2500


def test_invoice_month_query_excludes_purchase_month_and_keeps_bank_effective_date():
    purchase = transaction("purchase", -2500, MovementType.EXPENSE, "self", "2026-07-10", "N", "M")
    installment = transaction_with_invoice_month(purchase, "2026-09")
    bank = transaction("bank", -1000, MovementType.EXPENSE, "self", "2026-09-15", "N", "M")

    july = build_spending_summary([installment], month="2026-07")
    september = build_spending_summary([installment, bank], month="2026-09")
    assert july.total_minor_units == 0
    assert september.total_minor_units == 3500


def test_summary_can_filter_by_person_and_preserves_net_refunds() -> None:
    rows = [
        transaction("purchase", -1000, MovementType.EXPENSE, "self", "2026-01-03", "Needs", "Food"),
        transaction("refund", 250, MovementType.EXPENSE, "self", "2026-01-04", "Needs", "Food"),
        transaction("wife", -2000, MovementType.EXPENSE, "spouse", "2026-01-05", "Needs", "Food"),
    ]

    summary = build_spending_summary(rows, month="2026-01", person="self")

    assert summary.total_minor_units == 750
    assert summary.transaction_count == 2
    assert summary.by_category == {("Needs", "Food"): 750}


def test_brl_formatter_does_not_use_float() -> None:
    assert format_brl(123456) == "R$ 1.234,56"
    assert format_brl(-5) == "-R$ 0,05"
    assert format_brl(0) == "R$ 0,00"


def test_variation_display_keeps_sign_for_semantic_metric_arrow_and_color() -> None:
    assert format_variation_percent(-43.5) == "-43.5%"
    assert format_variation_percent(51.9) == "+51.9%"
    assert format_variation_percent(0.0) == "0.0%"
    assert format_variation_percent(None) is None


def test_empty_summary_has_zero_totals_and_empty_breakdowns() -> None:
    summary = build_spending_summary([], month="2026-01")

    assert summary.total_minor_units == 0
    assert summary.transaction_count == 0
    assert summary.by_person == {}
    assert summary.by_category == {}


def test_spending_trend_groups_daily_weekly_and_monthly_by_person_and_category() -> None:
    rows = [
        transaction("one", -1000, MovementType.EXPENSE, "self", "2026-02-01", "Needs", "Food"),
        transaction(
            "two", -2000, MovementType.EXPENSE, "spouse", "2026-02-02", "Leisure", "Cinema"
        ),
        transaction("three", 250, MovementType.EXPENSE, "self", "2026-02-03", "Needs", "Food"),
    ]

    daily = build_spending_trend(
        rows,
        start=date(2026, 2, 1),
        end=date(2026, 2, 28),
        granularity="day",
        dimension="person",
    )
    weekly = build_spending_trend(
        rows,
        start=date(2026, 2, 1),
        end=date(2026, 2, 28),
        granularity="week",
        dimension="macro",
    )
    monthly = build_spending_trend(
        rows,
        start=date(2026, 2, 1),
        end=date(2026, 2, 28),
        granularity="month",
        dimension="micro",
    )

    assert [(point.period, point.group, point.amount_minor_units) for point in daily] == [
        ("2026-02-01", "self", 1000),
        ("2026-02-02", "spouse", 2000),
        ("2026-02-03", "self", -250),
    ]
    assert {point.group for point in weekly} == {"Needs", "Leisure"}
    assert sum(point.amount_minor_units for point in weekly) == 2750
    assert {(point.period, point.group, point.amount_minor_units) for point in monthly} == {
        ("2026-02", "Food", 750),
        ("2026-02", "Cinema", 2000),
    }


def test_trend_excludes_pending_income_and_transfers() -> None:
    rows = [
        transaction(
            "confirmed", -1000, MovementType.EXPENSE, "self", "2026-02-01", "Needs", "Food"
        ),
        transaction("pending", -5000, MovementType.PENDING, "self", "2026-02-01", None, None),
        transaction("income", 10000, MovementType.INCOME, "self", "2026-02-01", None, None),
        transaction("transfer", -2000, MovementType.TRANSFER, "self", "2026-02-01", None, None),
    ]

    trend = build_spending_trend(
        rows,
        start=date(2026, 2, 1),
        end=date(2026, 2, 7),
        granularity="week",
        dimension="total",
    )

    assert len(trend) == 1
    assert trend[0].group == "Todos"
    assert trend[0].amount_minor_units == 1000


def test_top_expenses_returns_largest_outflows_in_period_and_skips_refunds() -> None:
    rows = [
        transaction("small", -500, MovementType.EXPENSE, "self", "2026-02-01", "Needs", "Food"),
        transaction(
            "large", -9000, MovementType.EXPENSE, "spouse", "2026-02-02", "Leisure", "Trip"
        ),
        transaction("refund", 7000, MovementType.EXPENSE, "self", "2026-02-03", "Needs", "Food"),
        transaction(
            "outside", -12000, MovementType.EXPENSE, "self", "2026-01-31", "Needs", "Other"
        ),
    ]

    result = top_expenses(rows, start=date(2026, 2, 1), end=date(2026, 2, 28), limit=1)

    assert len(result) == 1
    assert result[0].transaction_id == "large"
    assert result[0].amount_minor_units == 9000


def test_period_comparison_uses_previous_equal_inclusive_date_range() -> None:
    rows = [
        transaction("previous-a", -1000, MovementType.EXPENSE, "self", "2026-02-01", "N", "A"),
        transaction("previous-b", -1000, MovementType.EXPENSE, "self", "2026-02-02", "N", "B"),
        transaction("current-a", -3000, MovementType.EXPENSE, "self", "2026-02-03", "N", "A"),
        transaction("after", -9000, MovementType.EXPENSE, "self", "2026-02-04", "N", "A"),
    ]

    comparison = compare_spending_periods(rows, start=date(2026, 2, 3), end=date(2026, 2, 3))

    assert comparison.current_total_minor_units == 3000
    assert comparison.previous_total_minor_units == 1000
    assert comparison.previous_start == date(2026, 2, 2)
    assert comparison.previous_end == date(2026, 2, 2)
    assert comparison.variation_percent == 200.0


def test_period_comparison_handles_zero_baseline_without_infinite_percent() -> None:
    rows = [transaction("current", -100, MovementType.EXPENSE, "self", "2026-02-03", "N", "A")]

    comparison = compare_spending_periods(rows, start=date(2026, 2, 3), end=date(2026, 2, 3))

    assert comparison.previous_total_minor_units == 0
    assert comparison.variation_percent is None


def test_category_highlights_use_net_amounts_and_same_length_previous_period():
    rows = [
        transaction("previous", -5000, MovementType.EXPENSE, "self", "2026-02-01", "A", "Food"),
        transaction("current", -2000, MovementType.EXPENSE, "self", "2026-02-03", "A", "Food"),
        transaction("refund", 500, MovementType.EXPENSE, "self", "2026-02-04", "A", "Food"),
        transaction("other", -3000, MovementType.EXPENSE, "self", "2026-02-03", "B", "Food"),
        transaction("pending", -90000, MovementType.PENDING, "self", "2026-02-03", None, None),
    ]
    assert category_highlights(rows, start=date(2026, 2, 3), end=date(2026, 2, 4)) == (
        ("B", "Food"),
        3000,
        ("A", "Food"),
        5000,
        1500,
    )
    assert category_highlights([], start=date(2026, 2, 3), end=date(2026, 2, 4)) == (
        None,
        0,
        None,
        0,
        0,
    )


def transaction(
    identifier: str,
    amount_minor_units: int,
    movement_type: MovementType,
    person: str,
    occurred_on: str,
    macro: str | None,
    micro: str | None,
) -> StoredTransaction:
    return StoredTransaction(
        transaction_id=identifier,
        source_key="synthetic-source",
        description="DESCRIÇÃO FICTÍCIA",
        amount_minor_units=amount_minor_units,
        currency="BRL",
        movement_type=movement_type,
        person=Person(person),
        occurred_on=date.fromisoformat(occurred_on),
        posted_on=None,
        category=Category(macro, micro) if macro is not None and micro is not None else None,
        source_kind=SourceKind.BANK_ACCOUNT,
    )


def transaction_with_invoice_month(row: StoredTransaction, invoice_month: str) -> StoredTransaction:
    from dataclasses import replace

    return replace(row, invoice_month=invoice_month)
