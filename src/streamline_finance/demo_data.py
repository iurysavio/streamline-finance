"""Deterministic, fully synthetic data for an isolated interactive UI sandbox."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from streamline_finance.domain import Category, Money, MovementType, Person, SourceKind, Transaction
from streamline_finance.importers.nubank import PreviewTransaction

_MERCHANTS = (
    ("Mercado Fictício", "Necessidades básicas", "Mercado"),
    ("Cinema Exemplo", "Lazer", "Entretenimento"),
    ("Farmácia Inventada", "Necessidades básicas", "Saúde"),
    ("Restaurante Modelo", "Lazer", "Alimentação fora"),
    ("Transporte Teste", "Transporte", "Aplicativo"),
    ("Loja de Exemplo", "Desejos", "Compras"),
)
_PEOPLE = (Person.SELF, Person.SPOUSE, Person.SHARED)


def make_demo_transactions() -> tuple[Transaction, ...]:
    """Build stable synthetic history spanning 9 months plus reviewable pending rows."""
    rows: list[Transaction] = []
    for month_offset in range(9):
        month_index = date.today().year * 12 + date.today().month - 1 - month_offset
        year, month_zero = divmod(month_index, 12)
        month_number = month_zero + 1
        for index, (merchant, macro, micro) in enumerate(_MERCHANTS):
            person = _PEOPLE[(index + month_offset) % len(_PEOPLE)]
            day = min(2 + index * 3, 26)
            amount = 1800 + ((month_offset * 319 + index * 127) % 14500)
            rows.append(
                Transaction(
                    transaction_id=f"demo-{year}-{month_number:02d}-{index:02d}",
                    source_key="demo-generated",
                    description=merchant,
                    amount=Money(-amount),
                    movement_type=MovementType.EXPENSE,
                    person=person,
                    occurred_on=date(year, month_number, day),
                    category=Category(macro, micro),
                    source_kind=SourceKind.CREDIT_CARD,
                )
            )
    rows.extend(
        Transaction(
            transaction_id=f"demo-pending-{index:02d}",
            source_key="demo-generated",
            description=description,
            amount=Money(amount),
            movement_type=MovementType.PENDING,
            person=person,
            occurred_on=date.today().replace(day=min(5 + index, 26)),
            category=None,
            source_kind=SourceKind.BANK_ACCOUNT,
        )
        for index, (description, amount, person) in enumerate(
            (
                ("Compra Exemplo Sem Categoria", -4321, Person.SELF),
                ("Despesa fictícia sem categoria", -12000, Person.SPOUSE),
                ("Transferência Fictícia Pendente", -25000, Person.SHARED),
            ),
            1,
        )
    )
    rows.append(
        Transaction(
            transaction_id="demo-uncategorized-01",
            source_key="demo-generated",
            description="Compra Demonstrativa sem categoria",
            amount=Money(-6890),
            movement_type=MovementType.EXPENSE,
            person=Person.SELF,
            occurred_on=date.today().replace(day=min(12, 26)),
            category=None,
            source_kind=SourceKind.CREDIT_CARD,
        )
    )
    return tuple(rows)


def review_demo_transaction(
    transactions: tuple[Transaction, ...],
    transaction_id: str,
    *,
    movement_type: MovementType,
    macro: str | None = None,
    micro: str | None = None,
) -> tuple[Transaction, ...]:
    """Return a modified in-memory tuple; caller must never persist this demo result."""
    if movement_type is MovementType.PENDING:
        raise ValueError("choose a concrete demo movement type")
    if movement_type is MovementType.EXPENSE and (not macro or not micro):
        raise ValueError("demo expenses require macro and micro categories")
    result: list[Transaction] = []
    found = False
    for transaction in transactions:
        if transaction.transaction_id != transaction_id:
            result.append(transaction)
            continue
        if transaction.source_key != "demo-generated":
            raise ValueError("demo review only accepts generated demo transactions")
        found = True
        category = (
            Category(macro, micro)
            if movement_type is MovementType.EXPENSE and macro is not None and micro is not None
            else None
        )
        result.append(replace(transaction, movement_type=movement_type, category=category))
    if not found:
        raise KeyError("demo transaction not found")
    return tuple(result)


def append_demo_import(
    transactions: tuple[Transaction, ...],
    preview_transactions: tuple[PreviewTransaction, ...],
) -> tuple[Transaction, ...]:
    """Append only preview rows explicitly namespaced as an in-memory Demo Sandbox."""
    imported = tuple(
        replace(row.transaction, source_key="demo-generated") for row in preview_transactions
    )
    if any(row.source_key != "demo-generated" for row in imported):
        raise ValueError("Demo import rows must use the generated demo namespace")
    existing_ids = {row.transaction_id for row in transactions}
    if any(row.transaction_id in existing_ids for row in imported):
        raise ValueError("Demo import contains an identifier already present in this sandbox")
    return (*transactions, *imported)
