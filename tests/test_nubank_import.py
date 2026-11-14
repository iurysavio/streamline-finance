from datetime import date

import pytest

from streamline_finance.domain import MovementType, Person
from streamline_finance.importers.nubank import (
    ImportErrorCode,
    preview_nubank_csv,
)

VALID_CSV = (
    "JasData,Valor,Identificador,Descrição\n"
    "03/02/2026,-12.34,synthetic-row-001,COMPRA FICTICIA LOJA EXEMPLO\n"
    "04/02/2026,25.00,synthetic-row-002,TRANSFERENCIA FICTICIA\n"
)


def test_preview_parses_synthetic_rows_and_keeps_movements_pending() -> None:
    result = preview_nubank_csv(VALID_CSV, person=Person.SELF)

    assert result.can_confirm
    assert result.errors == ()
    assert len(result.transactions) == 2
    first, second = result.transactions
    assert first.transaction.transaction_id == "synthetic-row-001"
    assert first.transaction.amount.minor_units == -1234
    assert first.transaction.occurred_on == date(2026, 2, 3)
    assert first.transaction.posted_on is None
    assert first.transaction.person is Person.SELF
    assert first.transaction.movement_type is MovementType.PENDING
    assert second.transaction.amount.minor_units == 2500
    assert second.transaction.movement_type is MovementType.PENDING


def test_preview_tolerates_utf8_bom() -> None:
    result = preview_nubank_csv("\ufeff" + VALID_CSV, person=Person.SPOUSE)

    assert result.can_confirm
    assert result.transactions[0].transaction.person is Person.SPOUSE


def test_preview_preserves_every_source_column_including_unmapped_columns() -> None:
    csv_text = (
        "JasData,Valor,Identificador,Descrição,Campo Novo\n"
        "03/02/2026,-12.34,synthetic-row-001,COMPRA FICTICIA,valor sintetico\n"
    )

    result = preview_nubank_csv(csv_text, person=Person.SHARED)

    assert result.can_confirm
    assert result.transactions[0].source_fields == (
        ("Data", "03/02/2026"),
        ("Valor", "-12.34"),
        ("Identificador", "synthetic-row-001"),
        ("Descrição", "COMPRA FICTICIA"),
        ("Campo Novo", "valor sintetico"),
    )


def test_preview_accepts_original_export_typo_but_shows_clean_standard_header() -> None:
    csv_text = (
        "JasData,Valor,Identificador,Descrição\n"
        "03/02/2026,-12.34,synthetic-row-001,COMPRA FICTICIA\n"
    )

    result = preview_nubank_csv(csv_text, person=Person.SELF)

    assert result.can_confirm
    assert result.transactions[0].source_fields == (
        ("Data", "03/02/2026"),
        ("Valor", "-12.34"),
        ("Identificador", "synthetic-row-001"),
        ("Descrição", "COMPRA FICTICIA"),
    )


def test_preview_normalizes_surrounding_and_invisible_header_formatting() -> None:
    csv_text = (
        " JasData , Valor , Identificador , Descrição\u200b\n"
        "03/02/2026,-12.34,synthetic-row-001,COMPRA FICTICIA\n"
    )

    result = preview_nubank_csv(csv_text, person=Person.SELF)

    assert result.can_confirm
    assert result.transactions[0].source_fields[0] == ("Data", "03/02/2026")


@pytest.mark.parametrize(
    ("csv_text", "code"),
    [
        ("", ImportErrorCode.EMPTY_FILE),
        ("JasData;Valor;Identificador;Descrição\n", ImportErrorCode.HEADER_MISMATCH),
        (
            "JasData,Valor,Identificador,Descrição\n"
            "31/02/2026,-1.00,synthetic-row-001,TESTE FICTICIO\n",
            ImportErrorCode.INVALID_DATE,
        ),
        (
            "JasData,Valor,Identificador,Descrição\n"
            "03/02/2026,1.234,synthetic-row-001,TESTE FICTICIO\n",
            ImportErrorCode.INVALID_AMOUNT,
        ),
        (
            "JasData,Valor,Identificador,Descrição\n"
            '03/02/2026,"1,23",synthetic-row-001,TESTE FICTICIO\n',
            ImportErrorCode.INVALID_AMOUNT,
        ),
        (
            "JasData,Valor,Identificador,Descrição\n"
            "03/02/2026,-1e2,synthetic-row-001,TESTE FICTICIO\n",
            ImportErrorCode.INVALID_AMOUNT,
        ),
        (
            "JasData,Valor,Identificador,Descrição\n03/02/2026,-1.00,,TESTE FICTICIO\n",
            ImportErrorCode.MISSING_REQUIRED_VALUE,
        ),
    ],
)
def test_preview_reports_invalid_file_or_rows_without_exposing_values(
    csv_text: str,
    code: ImportErrorCode,
) -> None:
    result = preview_nubank_csv(csv_text, person=Person.SELF)

    assert not result.can_confirm
    assert any(error.code is code for error in result.errors)
    assert all("TESTE FICTICIO" not in error.message for error in result.errors)


def test_header_mismatch_reports_required_columns_without_row_data() -> None:
    result = preview_nubank_csv(
        "Data,Valor,ID,Descricao\n03/02/2026,-1.00,synthetic-01,FICTICIO\n",
        person=Person.SELF,
    )

    assert not result.can_confirm
    assert result.errors[0].code is ImportErrorCode.HEADER_MISMATCH
    assert "Data" in result.errors[0].message
    assert "FICTICIO" not in result.errors[0].message


def test_preview_blocks_confirmation_when_any_row_is_malformed() -> None:
    csv_text = (
        "JasData,Valor,Identificador,Descrição\n"
        "03/02/2026,-1.00,synthetic-01,LINHA FICTICIA VALIDA\n"
        "04/02/2026,-2.00,synthetic-02\n"
    )

    result = preview_nubank_csv(csv_text, person=Person.SELF)

    assert len(result.transactions) == 1
    assert not result.can_confirm
    assert result.errors[0].code is ImportErrorCode.MALFORMED_ROW
    assert result.errors[0].line_number == 3


def test_preview_skips_blank_lines_but_reports_them() -> None:
    csv_text = VALID_CSV.splitlines()[0] + "\n\n" + VALID_CSV.splitlines()[1] + "\n"

    result = preview_nubank_csv(csv_text, person=Person.SELF)

    assert result.can_confirm
    assert len(result.transactions) == 1
    assert result.skipped_blank_lines == ()


def test_preview_rejects_missing_columns_but_allows_extra_columns() -> None:
    missing = preview_nubank_csv(
        "JasData,Valor,Descrição\n03/02/2026,-1.00,FICTICIO\n",
        person=Person.SELF,
    )
    extra = preview_nubank_csv(
        "JasData,Valor,Identificador,Descrição,Campo Novo\n"
        "03/02/2026,-1.00,synthetic-01,FICTICIO,conteudo inventado\n",
        person=Person.SELF,
    )

    assert missing.errors[0].code is ImportErrorCode.HEADER_MISMATCH
    assert extra.can_confirm
    assert extra.transactions[0].source_fields[-1] == ("Campo Novo", "conteudo inventado")


def test_preview_detects_duplicate_headers_and_rows_with_extra_columns() -> None:
    duplicate_header = preview_nubank_csv(
        "JasData,Valor,Identificador,Identificador,Descrição\n",
        person=Person.SELF,
    )
    extra_cell = preview_nubank_csv(
        "JasData,Valor,Identificador,Descrição\n03/02/2026,-1.00,synthetic-01,FICTICIO,EXTRA\n",
        person=Person.SELF,
    )

    assert duplicate_header.errors[0].code is ImportErrorCode.HEADER_MISMATCH
    assert extra_cell.errors[0].code is ImportErrorCode.MALFORMED_ROW


def test_preview_is_in_memory_and_does_not_create_data_files(tmp_path) -> None:
    result = preview_nubank_csv(VALID_CSV, person=Person.SELF)

    assert result.can_confirm
    assert list(tmp_path.iterdir()) == []


def test_empty_required_fields_are_reported_by_name_only() -> None:
    csv_text = "JasData,Valor,Identificador,Descrição\n03/02/2026,-1.00,synthetic-row-001,\n"

    result = preview_nubank_csv(csv_text, person=Person.SELF)

    assert not result.can_confirm
    assert result.errors[0].code is ImportErrorCode.MISSING_REQUIRED_VALUE
    assert "Descrição" in result.errors[0].message
    assert "synthetic-row-001" not in result.errors[0].message
