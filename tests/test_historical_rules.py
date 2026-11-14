from io import BytesIO

from openpyxl import Workbook

from streamline_finance.rules import (
    HistoricalRuleError,
    load_expense_rules,
)
from streamline_finance.ui_pages import _historical_workbook_path


def test_loads_exact_description_rules_from_confirmed_mapping_using_synthetic_workbook() -> None:
    workbook_bytes = synthetic_workbook(
        [
            ["Data", "Valor", "Fluxo", "Tipo de Fluxo", "Classificação", "Observação"],
            ["2026-01-01", "10.00", "Mercado", "Necessidades", "Despesa", "Mercado Exemplo"],
            ["2026-01-02", "20.00", "Cinema", "Lazer", "Despesa", "Cinema Exemplo"],
            ["2026-01-03", "100.00", "Salário", "Receitas", "Receita", "Empregador Fictício"],
            ["2026-01-04", "5.00", "Sem detalhe", "Lazer", "Despesa", None],
        ]
    )

    result = load_expense_rules(workbook_bytes, confirm_column_mapping=True)

    assert len(result.rules) == 2
    assert result.rule_count == 2
    assert result.skipped_without_description == 1
    assert {
        (rule.description, rule.category.macro, rule.category.micro) for rule in result.rules
    } == {
        ("Mercado Exemplo", "Necessidades", "Mercado"),
        ("Cinema Exemplo", "Lazer", "Cinema"),
    }
    assert all(rule.rule_id.startswith("history-") for rule in result.rules)


def test_workbook_rules_require_explicit_confirmation_of_column_mapping() -> None:
    workbook_bytes = synthetic_workbook(
        [["Data", "Valor", "Fluxo", "Tipo de Fluxo", "Classificação", "Observação"]]
    )

    try:
        load_expense_rules(workbook_bytes, confirm_column_mapping=False)
    except HistoricalRuleError as error:
        assert error.code == "mapping_not_confirmed"
    else:
        raise AssertionError("mapping should require explicit confirmation")


def test_missing_required_workbook_columns_return_generic_safe_error() -> None:
    workbook_bytes = synthetic_workbook([["Data", "Valor", "Detalhe"]])

    try:
        load_expense_rules(workbook_bytes, confirm_column_mapping=True)
    except HistoricalRuleError as error:
        assert error.code == "missing_columns"
        assert "Observação" in error.message
    else:
        raise AssertionError("missing required workbook columns should fail")


def test_conflicting_description_categories_are_reported_not_arbitrarily_selected() -> None:
    workbook_bytes = synthetic_workbook(
        [
            ["Data", "Valor", "Fluxo", "Tipo de Fluxo", "Classificação", "Observação"],
            ["2026-01-01", "10.00", "Mercado", "Necessidades", "Despesa", "Loja Fictícia"],
            ["2026-01-02", "20.00", "Lazer", "Lazer", "Despesa", "Loja Fictícia"],
        ]
    )

    try:
        load_expense_rules(workbook_bytes, confirm_column_mapping=True)
    except HistoricalRuleError as error:
        assert error.code == "ambiguous_description"
    else:
        raise AssertionError("conflicting historical categories must not choose arbitrary rule")


def test_historical_workbook_searches_historic_then_reference_path_only(
    tmp_path, monkeypatch
) -> None:
    historic = tmp_path / "data" / "historical" / "ControleFinanceiro_VR-2.xlsx"
    reference = tmp_path / "data" / "reference" / "ControleFinanceiro.xlsx"
    unrecognized = tmp_path / "data" / "other" / "private.xlsx"
    historic.parent.mkdir(parents=True)
    reference.parent.mkdir(parents=True)
    unrecognized.parent.mkdir(parents=True)
    historic.touch()
    unrecognized.touch()
    monkeypatch.chdir(tmp_path)

    assert _historical_workbook_path() == historic

    historic.unlink()
    reference.touch()
    assert _historical_workbook_path() == reference
    reference.unlink()
    assert _historical_workbook_path() is None


def synthetic_workbook(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Entrada"
    sheet.append(["Relatório fictício"])
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
