from datetime import date

import pytest

from streamline_finance.domain import MovementType, Person
from streamline_finance.importers.c6_invoice import preview_c6_invoice
from streamline_finance.storage import FinanceRepository, ImportRejectedError

HEADER = (
    "Data de Compra;Nome no Cartão;Final do Cartão;Categoria;Descrição;"
    "Parcela;Valor (em US$);Cotação (em R$);Valor (em R$)\n"
)
CSV = (
    HEADER
    + "03/09/2026;Pessoa Fictícia;0000;Mercado;Loja Exemplo;Única;0.00;0.00;12.34\n"
    + "04/09/2026;Pessoa Fictícia;0000;Ajuste;Crédito Fictício;01/dez;0.00;0.00;-2.34\n"
).encode()


def test_c6_preview_preserves_raw_fields_and_normalizes_signs_without_classifying():
    result = preview_c6_invoice(CSV, person=Person.SELF, source_key="synthetic-card")
    assert result.can_confirm
    first, second = result.transactions
    assert first.transaction.amount.minor_units == -1234
    assert second.transaction.amount.minor_units == 234
    assert first.transaction.occurred_on == date(2026, 9, 3)
    assert first.transaction.movement_type is MovementType.PENDING
    assert second.transaction.movement_type is MovementType.PENDING
    assert dict(second.source_fields)["Parcela"] == "01/dez"
    assert dict(first.source_fields)["Valor (em US$)"] == "0.00"


def test_c6_preview_preserves_identical_rows_and_is_stable_for_same_file():
    row = "03/09/2026;Pessoa Fictícia;0000;Mercado;Loja Exemplo;Única;0.00;0.00;12.34\n"
    content = (HEADER + row + row).encode()
    first = preview_c6_invoice(content, person=Person.SELF, source_key="synthetic-card")
    second = preview_c6_invoice(content, person=Person.SELF, source_key="synthetic-card")
    ids = [item.transaction.transaction_id for item in first.transactions]
    assert len(set(ids)) == 2
    assert ids == [item.transaction.transaction_id for item in second.transactions]


def test_c6_preview_rejects_invalid_values_and_unknown_headers_without_echoing_rows():
    bad = CSV.replace(b"12.34", b"12.345")
    result = preview_c6_invoice(bad, person=Person.SELF, source_key="synthetic-card")
    assert not result.can_confirm
    assert all("Loja Exemplo" not in error.message for error in result.errors)
    assert not preview_c6_invoice(b"wrong;header\n", person=Person.SELF).can_confirm


def test_invoice_preview_cannot_be_persisted_without_competence(tmp_path):
    preview = preview_c6_invoice(CSV, person=Person.SELF, source_key="synthetic-card")
    with FinanceRepository(tmp_path / "db" / "finance.sqlite3") as repository:
        with pytest.raises(ImportRejectedError):
            repository.confirm_import(preview, source_key="synthetic-card", content=CSV)
        assert repository.list_imports() == ()
