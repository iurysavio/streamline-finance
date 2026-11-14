from streamline_finance.demo_data import (
    append_demo_import,
    make_demo_transactions,
    review_demo_transaction,
)
from streamline_finance.domain import MovementType, Person
from streamline_finance.importers.nubank import preview_nubank_csv


def test_demo_data_is_deterministic_and_contains_multiple_months_people_and_categories() -> None:
    first = make_demo_transactions()
    second = make_demo_transactions()

    assert first == second
    assert len(first) >= 20
    assert len({row.occurred_on.strftime("%Y-%m") for row in first}) >= 6
    assert {row.person.value for row in first} == {"self", "spouse", "shared"}
    assert {row.movement_type for row in first} >= {MovementType.EXPENSE, MovementType.PENDING}


def test_demo_review_changes_only_the_passed_in_memory_copy() -> None:
    original = make_demo_transactions()
    reviewed = review_demo_transaction(
        original,
        "demo-pending-01",
        movement_type=MovementType.EXPENSE,
        macro="Necessidades básicas",
        micro="Mercado",
    )

    original_row = next(row for row in original if row.transaction_id == "demo-pending-01")
    assert original_row.movement_type is MovementType.PENDING
    reviewed_row = next(row for row in reviewed if row.transaction_id == "demo-pending-01")
    assert reviewed_row.movement_type is MovementType.EXPENSE
    assert reviewed_row.category is not None
    assert reviewed_row.category.macro == "Necessidades básicas"


def test_demo_csv_import_keeps_rows_only_in_memory_and_uses_demo_namespace() -> None:
    original = make_demo_transactions()
    preview = preview_nubank_csv(
        b"JasData,Valor,Identificador,Descri\xc3\xa7\xc3\xa3o\n"
        b"03/02/2026,-12.34,demo-import-id,COMPRA FICTICIA\n",
        person=Person.SELF,
        source_key="temporary-upload",
    )

    sandbox = append_demo_import(original, preview.transactions)

    assert len(sandbox) == len(original) + 1
    assert len(original) == 58
    assert sandbox[-1].source_key == "demo-generated"
    assert sandbox[-1].transaction_id == "demo-import-id"
