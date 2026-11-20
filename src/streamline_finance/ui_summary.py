"""Read-only aggregates used by the Streamlit overview and monthly reports."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from streamline_finance.domain import Transaction
from streamline_finance.storage import StoredTransaction


@dataclass(frozen=True, slots=True)
class SpendingSummary:
    month: str
    total_minor_units: int
    transaction_count: int
    by_person: dict[str, int]
    by_category: dict[tuple[str, str], int]


@dataclass(frozen=True, slots=True)
class SpendingTrendPoint:
    period: str
    group: str
    amount_minor_units: int


@dataclass(frozen=True, slots=True)
class TopExpense:
    transaction_id: str
    occurred_on: date
    description: str
    person: str
    category_macro: str
    category_micro: str
    amount_minor_units: int
    invoice_month: str | None = None


@dataclass(frozen=True, slots=True)
class PeriodComparison:
    current_start: date
    current_end: date
    previous_start: date
    previous_end: date
    current_total_minor_units: int
    previous_total_minor_units: int
    variation_minor_units: int
    variation_percent: float | None


def build_spending_trend(
    transactions: Iterable[StoredTransaction | Transaction],
    *,
    start: date,
    end: date,
    granularity: str,
    dimension: str,
) -> tuple[SpendingTrendPoint, ...]:
    """Return confirmed net expenses by time bucket and one selected breakdown."""
    if start > end:
        raise ValueError("start date must be before end date")
    if granularity not in {"day", "week", "month"}:
        raise ValueError("granularity must be day, week, or month")
    if dimension not in {"total", "person", "macro", "micro"}:
        raise ValueError("dimension must be total, person, macro, or micro")

    totals: dict[tuple[str, str], int] = defaultdict(int)
    for row in transactions:
        report_date = _report_date(row)
        if row.movement_type.value != "expense" or not in_reporting_range(row, start, end):
            continue
        period = _period_key(report_date, granularity)
        if dimension == "total":
            group = "Todos"
        elif dimension == "person":
            group = row.person.value
        elif dimension == "macro":
            group = row.category.macro if row.category else "Sem categoria"
        else:
            group = row.category.micro if row.category else "Sem categoria"
        amount_minor_units = (
            row.amount_minor_units if isinstance(row, StoredTransaction) else row.amount.minor_units
        )
        totals[(period, group)] -= amount_minor_units

    return tuple(
        SpendingTrendPoint(period, group, amount)
        for (period, group), amount in sorted(totals.items())
    )


def build_spending_summary(
    transactions: Iterable[StoredTransaction],
    *,
    month: str,
    person: str | None = None,
) -> SpendingSummary:
    """Sum only confirmed expenses; incoming amounts naturally offset refunds."""
    if len(month) != 7 or month[4] != "-" or not month[:4].isdigit() or not month[5:].isdigit():
        raise ValueError("month must use YYYY-MM format")

    eligible = [
        row
        for row in transactions
        if row.movement_type.value == "expense"
        and _report_date(row).strftime("%Y-%m") == month
        and (person is None or row.person.value == person)
    ]
    # Stored expense rows are signed cash movements (purchases negative, refunds positive).
    # Reports display spending as positive; refunds reduce the spending total.
    total = -sum(row.amount_minor_units for row in eligible)
    by_person: dict[str, int] = defaultdict(int)
    by_category: dict[tuple[str, str], int] = defaultdict(int)
    for row in eligible:
        by_person[row.person.value] -= row.amount_minor_units
        key = (
            (row.category.macro, row.category.micro)
            if row.category is not None
            else ("Sem categoria", "Revisar")
        )
        by_category[key] -= row.amount_minor_units

    return SpendingSummary(
        month=month,
        total_minor_units=total,
        transaction_count=len(eligible),
        by_person=dict(by_person),
        by_category=dict(by_category),
    )


def format_brl(minor_units: int) -> str:
    """Format integer cents without binary floating-point."""
    absolute = abs(minor_units)
    whole, cents = divmod(absolute, 100)
    grouped = f"{whole:,}".replace(",", ".")
    sign = "-" if minor_units < 0 else ""
    return f"{sign}R$ {grouped},{cents:02d}"


def format_variation_percent(value: float | None) -> str | None:
    """Return a signed percentage string so Streamlit's metric adds directional color/arrow."""
    if value is None:
        return None
    return f"{value:+.1f}%" if value != 0 else "0.0%"


def top_expenses(
    transactions: Iterable[StoredTransaction | Transaction],
    *,
    start: date,
    end: date,
    person: str | None = None,
    limit: int | None = 10,
) -> tuple[TopExpense, ...]:
    """Return largest purchases by individual value, not grouped merchant totals."""
    if start > end:
        raise ValueError("start date must be before end date")
    if limit is not None and (limit < 1 or limit > 100):
        raise ValueError("limit must be between 1 and 100")
    rows: list[TopExpense] = []
    for row in transactions:
        if row.movement_type.value != "expense" or not in_reporting_range(row, start, end):
            continue
        if person is not None and row.person.value != person:
            continue
        amount = (
            row.amount_minor_units if isinstance(row, StoredTransaction) else row.amount.minor_units
        )
        if amount >= 0:
            continue
        rows.append(
            TopExpense(
                transaction_id=row.transaction_id,
                occurred_on=row.occurred_on,
                description=row.description,
                person=row.person.value,
                category_macro=row.category.macro if row.category else "Sem categoria",
                category_micro=row.category.micro if row.category else "Revisar",
                amount_minor_units=-amount,
                invoice_month=row.invoice_month if isinstance(row, StoredTransaction) else None,
            )
        )
    return tuple(
        sorted(
            rows, key=lambda item: (-item.amount_minor_units, item.occurred_on, item.transaction_id)
        )[:limit]
    )


def category_highlights(transactions, *, start: date, end: date):
    """Return largest net category and largest absolute reduction, in integer cents."""
    duration = (end - start).days + 1
    previous_start = start - timedelta(days=duration)
    previous_end = start - timedelta(days=1)
    current: dict[tuple[str, str], int] = defaultdict(int)
    previous: dict[tuple[str, str], int] = defaultdict(int)
    for row in transactions:
        if row.movement_type.value != "expense" or row.category is None:
            continue
        target = (
            current
            if in_reporting_range(row, start, end)
            else previous
            if in_reporting_range(row, previous_start, previous_end)
            else None
        )
        if target is not None:
            amount = (
                row.amount_minor_units
                if isinstance(row, StoredTransaction)
                else row.amount.minor_units
            )
            target[(row.category.macro, row.category.micro)] -= amount
    largest = max(sorted(current), key=current.get) if current else None
    reductions = {
        key: previous.get(key, 0) - current.get(key, 0) for key in current.keys() | previous.keys()
    }
    best = max(sorted(reductions), key=reductions.get) if reductions else None
    if best is not None and reductions[best] <= 0:
        best = None
    return (largest, current.get(largest, 0), best, previous.get(best, 0), current.get(best, 0))


def compare_spending_periods(
    transactions: Iterable[StoredTransaction | Transaction],
    *,
    start: date,
    end: date,
    person: str | None = None,
) -> PeriodComparison:
    """Compare inclusive current range with the immediately preceding equal day count."""
    if start > end:
        raise ValueError("start date must be before end date")
    history = tuple(transactions)
    duration = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=duration - 1)
    current_total = (
        sum(
            point.amount_minor_units
            for point in build_spending_trend(
                history, start=start, end=end, granularity="day", dimension="total"
            )
            if person is None
        )
        if person is None
        else _period_spending(history, start, end, person)
    )
    previous_total = (
        sum(
            point.amount_minor_units
            for point in build_spending_trend(
                history,
                start=previous_start,
                end=previous_end,
                granularity="day",
                dimension="total",
            )
        )
        if person is None
        else _period_spending(history, previous_start, previous_end, person)
    )
    variation = current_total - previous_total
    percent = (variation * 100 / previous_total) if previous_total else None
    return PeriodComparison(
        current_start=start,
        current_end=end,
        previous_start=previous_start,
        previous_end=previous_end,
        current_total_minor_units=current_total,
        previous_total_minor_units=previous_total,
        variation_minor_units=variation,
        variation_percent=percent,
    )


def _period_spending(
    transactions: Iterable[StoredTransaction | Transaction],
    start: date,
    end: date,
    person: str,
) -> int:
    total = 0
    for row in transactions:
        if (
            row.movement_type.value == "expense"
            and row.person.value == person
            and in_reporting_range(row, start, end)
        ):
            amount = (
                row.amount_minor_units
                if isinstance(row, StoredTransaction)
                else row.amount.minor_units
            )
            total -= amount
    return total


def _period_key(value: date, granularity: str) -> str:
    if granularity == "day":
        return value.isoformat()
    if granularity == "month":
        return value.strftime("%Y-%m")
    week_start = value - timedelta(days=value.weekday())
    return week_start.isoformat()


def _report_date(row: StoredTransaction | Transaction) -> date:
    """Use statement competence for reports while preserving the original purchase date."""
    month = row.invoice_month if isinstance(row, StoredTransaction) else None
    return date.fromisoformat(f"{month}-01") if month is not None else row.occurred_on


def in_reporting_range(row: StoredTransaction | Transaction, start: date, end: date) -> bool:
    """Date-filter bank transactions by day and card invoices by inclusive statement month."""
    month = row.invoice_month if isinstance(row, StoredTransaction) else None
    if month is not None:
        return start.strftime("%Y-%m") <= month <= end.strftime("%Y-%m")
    return start <= row.occurred_on <= end
