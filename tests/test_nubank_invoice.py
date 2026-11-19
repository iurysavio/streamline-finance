from datetime import date

from streamline_finance.domain import MovementType, Person
from streamline_finance.importers.nubank_invoice import preview_nubank_invoice

CSV = (
    'date,title,amount\n2026-09-03,Compra Fictícia,"12,34"\n2026-09-04,Crédito Fictício,"- 2,34"\n'
).encode()


def test_invoice_preview_normalizes_amount_and_preserves_raw_fields():
    result = preview_nubank_invoice(CSV, person=Person.SELF, source_key="synthetic-card")
    assert result.can_confirm
    first, second = result.transactions
    assert first.transaction.amount.minor_units == -1234
    assert second.transaction.amount.minor_units == 234
    assert first.transaction.occurred_on == date(2026, 9, 3)
    assert all(row.transaction.movement_type is MovementType.PENDING for row in result.transactions)
    assert dict(second.source_fields)["amount"] == "- 2,34"


def test_invoice_rejects_malformed_values_without_leaking_rows():
    result = preview_nubank_invoice(CSV.replace(b"12,34", b"12,345"), person=Person.SELF)
    assert not result.can_confirm
    assert all("Compra Fictícia" not in error.message for error in result.errors)
