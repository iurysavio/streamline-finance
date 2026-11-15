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

    result = load_expense_rules(workbook_bytes, confirm_column_mapping=True)
    assert result.rules == ()
    assert result.excluded_descriptions == ("loja fictícia",)


def test_incomplete_or_conflicting_descriptions_do_not_hide_valid_rules():
    workbook_bytes = synthetic_workbook(
        [
            ["Data", "Valor", "Fluxo", "Tipo de Fluxo", "Classificação", "Observação"],
            [None, None, "Mercado", "Casa", "Despesa", "Incompleta"],
            [None, None, None, "Casa", "Despesa", "INCOMPLETA"],
            [None, None, "Mercado", "Casa", "Despesa", "Incompleta"],
            [None, None, "Mercado", "Casa", "Despesa", "Válida"],
        ]
    )
    result = load_expense_rules(workbook_bytes, confirm_column_mapping=True)
    assert [rule.description for rule in result.rules] == ["Válida"]
    assert result.excluded_descriptions == ("incompleta",)
    assert result.skipped_incomplete_categories == 1
    assert result.issue_rows == (
        (3, "Categoria incompleta"),
        (4, "Categoria incompleta"),
        (5, "Categoria incompleta"),
    )


def test_incomplete_workbook_description_blocks_matching_app_history(tmp_path, monkeypatch):
    import streamline_finance.ui_pages as ui

    workbook = tmp_path / "synthetic.xlsx"
    workbook.write_bytes(
        synthetic_workbook(
            [
                ["Data", "Valor", "Fluxo", "Tipo de Fluxo", "Classificação", "Observação"],
                [None, None, None, "Casa", "Despesa", "Loja fictícia"],
            ]
        )
    )

    class Response:
        status_code = 200

        def json(self):
            return {
                "transactions": [
                    {
                        "description": "LOJA FICTÍCIA",
                        "category": {"macro": "Casa", "micro": "Mercado"},
                    }
                ]
            }

    monkeypatch.setattr(
        ui, "_api_get", lambda path, **kwargs: Response() if path == "/transactions" else None
    )
    monkeypatch.setattr(ui, "_historical_workbook_path", lambda: workbook)
    monkeypatch.setattr(ui.st, "checkbox", lambda *args, **kwargs: True)
    monkeypatch.setattr(ui.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui.st, "dataframe", lambda *args, **kwargs: None)
    assert ui._review_rules() == []


def test_historical_workbook_searches_historic_then_reference_path_only(
    tmp_path, monkeypatch
) -> None:
    historic = tmp_path / "data" / "historical" / "ControleFinanceiro_VR-2.xlsx"
    current = tmp_path / "data" / "historical" / "ControleFinanceiro_VR.xlsx"
    reference = tmp_path / "data" / "reference" / "ControleFinanceiro.xlsx"
    unrecognized = tmp_path / "data" / "other" / "private.xlsx"
    historic.parent.mkdir(parents=True)
    reference.parent.mkdir(parents=True)
    unrecognized.parent.mkdir(parents=True)
    historic.touch()
    unrecognized.touch()
    monkeypatch.chdir(tmp_path)

    assert _historical_workbook_path() == historic

    current.touch()
    assert _historical_workbook_path() == current
    current.unlink()
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
