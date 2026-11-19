from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_dashboard_renders_empty_state_without_starting_network_calls() -> None:
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()

    assert not app.exception
    assert any("Análise de gastos" in title.value for title in app.title)
    assert any("Dados para explorar" == radio.label for radio in app.radio)
    assert any(radio.value == "Demo — fictício" for radio in app.radio)
    assert any(select.label == "Detalhar por" for select in app.selectbox)


def test_demo_analysis_has_synthetic_interactive_trend_chart(monkeypatch) -> None:
    import plotly.graph_objects as go

    import streamline_finance.ui_pages as ui_pages

    charts = []

    def capture_chart(chart, **kwargs):
        charts.append(chart)

    monkeypatch.setattr(ui_pages.st, "plotly_chart", capture_chart)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()

    assert not app.exception
    assert len(charts) == 2
    assert isinstance(charts[0], go.Figure)
    spec = charts[0].to_dict()
    assert "%{customdata}" in spec["data"][0]["hovertemplate"]


def test_import_page_has_synthetic_flow_and_explicit_confirmation_control() -> None:
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    app.switch_page("pages/2_Importar.py").run()
    app.radio(key="data_mode_label").set_value("Demo — fictício").run()

    assert not app.exception
    assert any("CSV sintético" == uploader.label for uploader in app.file_uploader)
    assert any("Demo Sandbox" in warning.value for warning in app.warning)


def test_native_page_navigation_lists_analysis_import_review_and_company_title() -> None:
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()

    assert not app.exception
    assert any(title.value == "Finanças da Família Sávio" for title in app.title)
    assert app.switch_page("pages/2_Importar.py").run().title[0].value == "Importar extrato"
    assert app.switch_page("pages/3_Revisar.py").run().title[0].value == "Revisar movimentações"


def test_import_flow_renders_preview_and_confirm_only_after_successful_api_response() -> None:
    import tempfile
    from unittest.mock import patch

    import httpx2
    from fastapi.testclient import TestClient

    from streamline_finance.api import create_app
    from streamline_finance.storage import FinanceRepository

    sandbox = tempfile.TemporaryDirectory()
    repository = FinanceRepository(Path(sandbox.name) / "data" / "db" / "finance.sqlite3")
    client = TestClient(create_app(repository=repository))

    def local_post(url, *, data=None, files=None, json=None, timeout=2.0):
        path = url.removeprefix("http://127.0.0.1:8000")
        if path == "/imports/preview":
            return client.post(path, data=data, files=files)
        if path == "/imports/confirm":
            return client.post(path, data=data, files=files)
        return client.post(path, data=data, files=files, json=json)

    def local_get(url, *, params=None, timeout=2.0):
        path = url.removeprefix("http://127.0.0.1:8000")
        return client.get(path, params=params)

    try:
        with (
            patch.object(httpx2, "post", side_effect=local_post),
            patch.object(httpx2, "get", side_effect=local_get),
        ):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
            app.radio(key="data_mode_label").set_value("Meus dados locais").run()
            app.switch_page("pages/2_Importar.py").run()
            app.text_input[0].set_value("synthetic-ui-account").run()
            app.session_state["source_mapping_ack"] = True
            app.session_state["import_preview"] = {
                "content": (
                    ROOT / "tests" / "fixtures" / "nubank_statement_synthetic.csv"
                ).read_bytes(),
                "filename": "synthetic.csv",
                "source_key": "synthetic-ui-account",
                "person": "self",
                "source_kind": "bank_account",
                "response": {
                    "can_confirm": True,
                    "transaction_count": 1,
                    "transactions": [
                        {
                            "transaction_id": "synthetic-001",
                            "description": "COMPRA FICTICIA",
                            "amount_minor_units": -100,
                            "person": "self",
                            "occurred_on": "2026-02-03",
                            "source_fields": {"Descrição": "COMPRA FICTICIA"},
                        }
                    ],
                    "errors": [],
                },
            }
            app.run()
            app.session_state["confirm_import_ack"] = True
            app.run()

            assert not app.exception
            assert any(header.value == "Prévia antes de salvar" for header in app.subheader)
            assert any(button.label == "Confirmar importação" for button in app.button)
            assert repository.list_imports() == ()

            app.button[-1].click().run(timeout=20)
            assert not app.exception
            assert len(repository.list_imports()) == 1
    finally:
        client.close()
        repository.close()
        sandbox.cleanup()


def test_review_page_shows_pending_transactions_and_manual_category_confirmation() -> None:
    import tempfile
    from unittest.mock import patch

    import httpx2
    from fastapi.testclient import TestClient

    from streamline_finance.api import create_app
    from streamline_finance.domain import Person
    from streamline_finance.importers.nubank import preview_nubank_csv
    from streamline_finance.storage import FinanceRepository

    sandbox = tempfile.TemporaryDirectory()
    repository = FinanceRepository(Path(sandbox.name) / "data" / "db" / "finance.sqlite3")
    content = (ROOT / "tests" / "fixtures" / "nubank_statement_synthetic.csv").read_bytes()
    repository.confirm_import(
        preview_nubank_csv(
            content,
            person=Person.SELF,
            source_key="synthetic-review-account",
        ),
        source_key="synthetic-review-account",
        content=content,
    )
    client = TestClient(create_app(repository=repository))

    def local_get(url, *, params=None, timeout=2.0):
        return client.get(url.removeprefix("http://127.0.0.1:8000"), params=params)

    def local_post(url, *, data=None, files=None, json=None, timeout=2.0):
        return client.post(
            url.removeprefix("http://127.0.0.1:8000"),
            data=data,
            files=files,
            json=json,
        )

    try:
        with (
            patch.object(httpx2, "get", side_effect=local_get),
            patch.object(httpx2, "post", side_effect=local_post),
        ):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
            app.radio(key="data_mode_label").set_value("Meus dados locais").run()
            app.switch_page("pages/3_Revisar.py").run()
            assert not app.exception
            assert len(app.expander) == 3
            assert any(item.label == "Macro categoria" for item in app.selectbox)
            assert any(button.label == "Confirmar natureza e categoria" for button in app.button)
    finally:
        client.close()
        repository.close()
        sandbox.cleanup()


def test_confirmed_history_suggests_for_new_pending_import_without_classifying(
    tmp_path, monkeypatch
):
    import httpx2
    from fastapi.testclient import TestClient

    from streamline_finance.api import create_app
    from streamline_finance.domain import Category, MovementType, Person
    from streamline_finance.importers.nubank import preview_nubank_csv
    from streamline_finance.storage import FinanceRepository

    database = tmp_path / "data" / "db" / "finance.sqlite3"
    first = (ROOT / "tests" / "fixtures" / "nubank_statement_synthetic.csv").read_bytes()
    second = first.replace(b"synthetic-transaction-001", b"synthetic-new-001").replace(
        b"synthetic-transaction-002", b"synthetic-new-002"
    )
    with FinanceRepository(database) as repository:
        repository.confirm_import(
            preview_nubank_csv(first, person=Person.SELF, source_key="test"),
            source_key="test",
            content=first,
        )
        repository.review_movement_type(
            "test",
            "synthetic-transaction-001",
            MovementType.EXPENSE,
            confirm=True,
            category=Category("Casa", "Mercado"),
        )
        repository.confirm_import(
            preview_nubank_csv(second, person=Person.SELF, source_key="test"),
            source_key="test",
            content=second,
        )

    with (
        FinanceRepository(database) as repository,
        TestClient(create_app(repository=repository)) as client,
    ):
        monkeypatch.setattr(
            httpx2,
            "get",
            lambda url, **kwargs: client.get(
                url.removeprefix("http://127.0.0.1:8000"), params=kwargs.get("params")
            ),
        )
        monkeypatch.setattr(
            httpx2,
            "post",
            lambda url, **kwargs: client.post(
                url.removeprefix("http://127.0.0.1:8000"), json=kwargs.get("json")
            ),
        )
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        app.radio(key="data_mode_label").set_value("Meus dados locais").run()
        app.switch_page("pages/2_Importar.py").run()
        app.text_input[0].set_value("test").run()
        payload = client.post(
            "/imports/preview",
            data={"source_key": "test", "person": "self"},
            files={"file": ("synthetic.csv", second, "text/csv")},
        ).json()
        app.session_state["import_preview"] = {
            "content": second,
            "filename": "synthetic.csv",
            "source_key": "test",
            "person": "self",
            "source_kind": "bank_account",
            "response": payload,
        }
        app.run()
        assert (
            "Casa / Mercado (aplicação)"
            in app.dataframe[0].value["Categoria sugerida (se despesa)"].values
        )
        app.switch_page("pages/3_Revisar.py").run()
        assert not app.exception
        assert any("Casa / Mercado (aplicação)" in info.value for info in app.info)
        assert (
            repository.get_transaction("synthetic-new-001", source_key="test").movement_type
            is MovementType.PENDING
        )
        app.button(key="use-suggestion-test-synthetic-new-001").click().run()
        assert app.selectbox(key="macro-test-synthetic-new-001").value == "Casa"
        assert app.selectbox(key="micro-test-synthetic-new-001").value == "Mercado"
        assert (
            repository.get_transaction("synthetic-new-001", source_key="test").movement_type
            is MovementType.PENDING
        )
        app.button(key="confirm-type-test-synthetic-new-001").click().run()
        assert repository.get_transaction(
            "synthetic-new-001", source_key="test"
        ).category == Category("Casa", "Mercado")


def test_preview_suggestion_labels_explain_sources_and_conflicts():
    from streamline_finance.categorization import CategorizationRule
    from streamline_finance.domain import Category
    from streamline_finance.ui_pages import _suggestion_label

    rules = [
        CategorizationRule("app-history", "Loja fictícia", Category("Casa", "Mercado")),
        CategorizationRule("history-1", "LOJA FICTÍCIA", Category("Casa", "Mercado")),
    ]
    assert _suggestion_label("loja   fictícia", rules) == "Casa / Mercado (aplicação e planilha)"
    rules.append(CategorizationRule("history-2", "loja fictícia", Category("Lazer", "Comida")))
    assert _suggestion_label("loja fictícia", rules) == "Conflito — revisar"
    assert _suggestion_label("outra loja", rules) == "Sem sugestão"


def test_expense_description_splits_only_first_delimiter():
    from streamline_finance.ui_pages import _split_description

    assert _split_description("PIX - Loja Exemplo - Filial") == ("PIX", "Loja Exemplo - Filial")
    assert _split_description("Loja Exemplo") == ("Não informado", "Loja Exemplo")


def test_trend_hover_uses_exact_brl_label():
    from streamline_finance.ui_pages import _trend_chart
    from streamline_finance.ui_summary import SpendingTrendPoint

    chart = _trend_chart((SpendingTrendPoint("2026-01", "Todos", 123456),), "month", "total")
    assert list(chart.data[0].customdata) == ["R$ 1.234,56"]
    assert "%{customdata}" in chart.data[0].hovertemplate


def test_expense_filters_apply_to_all_period_rows():
    from datetime import date, timedelta

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    today = date.today()
    app.date_input(key="analysis_date_range").set_value((today - timedelta(days=270), today)).run()
    assert len(app.dataframe[0].value) > 10
    app.multiselect(key="expense-filter-Macro").select("Lazer").run()
    assert not app.exception
    assert set(app.dataframe[0].value["Macro"]) == {"Lazer"}


def test_demo_csv_upload_stays_in_session_memory_and_never_enters_sqlite() -> None:
    import tempfile
    from unittest.mock import patch

    import httpx2
    from fastapi.testclient import TestClient

    from streamline_finance.api import create_app
    from streamline_finance.storage import FinanceRepository

    sandbox = tempfile.TemporaryDirectory()
    repository = FinanceRepository(Path(sandbox.name) / "data" / "db" / "finance.sqlite3")
    client = TestClient(create_app(repository=repository))

    def local_post(url, *, data=None, files=None, json=None, timeout=2.0):
        return client.post(
            url.removeprefix("http://127.0.0.1:8000"),
            data=data,
            files=files,
            json=json,
        )

    try:
        with patch.object(httpx2, "post", side_effect=local_post):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
            app.switch_page("pages/2_Importar.py").run()
            app.file_uploader[0].upload(
                "demo-upload.csv",
                (ROOT / "tests" / "fixtures" / "nubank_statement_synthetic.csv").read_bytes(),
                "text/csv",
            ).run()
            app.button[0].click().run()
            assert not app.exception
            assert any(
                button.label == "Adicionar ao Demo Sandbox em memória" for button in app.button
            )
            assert repository.list_imports() == ()
            app.button[-1].click().run()
            assert not app.exception
            assert repository.list_imports() == ()
            assert repository.list_transactions() == ()
            assert any(
                row.transaction_id == "synthetic-transaction-001"
                for row in app.session_state["demo_transactions"]
            )
    finally:
        client.close()
        repository.close()
        sandbox.cleanup()


def test_analysis_renders_plotly_trend_with_formatted_values(monkeypatch) -> None:
    import plotly.graph_objects as go

    import streamline_finance.ui_pages as ui_pages

    charts = []
    monkeypatch.setattr(ui_pages.st, "plotly_chart", lambda chart, **kwargs: charts.append(chart))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()

    assert not app.exception
    assert len(charts) == 2
    assert isinstance(charts[0], go.Figure)
    specification = charts[0].to_dict()
    assert all(value.startswith("R$ ") for value in specification["data"][0]["customdata"])


def test_analysis_renders_only_trend_and_comparison_charts_top_expenses_is_table(
    monkeypatch,
) -> None:
    import plotly.graph_objects as go

    import streamline_finance.ui_pages as ui_pages

    charts = []
    monkeypatch.setattr(ui_pages.st, "plotly_chart", lambda chart, **kwargs: charts.append(chart))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()

    assert not app.exception
    assert len(charts) == 2
    assert all(isinstance(chart, go.Figure) for chart in charts)
    chart_titles = [chart.layout.title.text or "" for chart in charts]
    assert "Gasto líquido entre períodos iguais" in chart_titles
    assert not any("Top 10" in title for title in chart_titles)
    assert len(app.dataframe) >= 1


def test_period_comparison_chart_has_visible_bar_value_labels() -> None:
    from datetime import date

    from streamline_finance.ui_pages import _period_comparison_chart
    from streamline_finance.ui_summary import compare_spending_periods

    chart = _period_comparison_chart(
        compare_spending_periods([], start=date(2026, 2, 1), end=date(2026, 2, 7))
    )
    spec = chart.to_dict()

    assert spec["data"][0]["text"] == ["R$ 0,00", "R$ 0,00"]
    assert spec["data"][0]["marker"]["color"] == "#4F8BF9"
    assert spec["layout"]["yaxis"]["rangemode"] == "tozero"


def test_comparison_cards_are_rendered_before_comparison_chart(monkeypatch) -> None:
    import streamline_finance.ui_pages as ui_pages

    monkeypatch.setattr(ui_pages.st, "plotly_chart", lambda *args, **kwargs: None)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
    comparison_header_index = next(
        index
        for index, element in enumerate(app.main)
        if isinstance(getattr(element, "value", None), str)
        and element.value == "↔️ Comparação com o período anterior"
    )

    variation_index = next(
        index
        for index, element in enumerate(app.main)
        if isinstance(getattr(element, "value", None), str) and "Variação" in element.value
    )
    assert comparison_header_index < variation_index


def test_variation_card_uses_green_down_arrow_for_decrease_and_red_up_arrow_for_increase(
    monkeypatch,
) -> None:
    from datetime import date

    import streamline_finance.ui_pages as ui_pages

    captured = []

    class MetricCapture:
        def __init__(self):
            self.metrics = []

        def date_input(self, label, **kwargs):
            return (date(2026, 1, 1), date(2026, 1, 7))

        def radio(self, label, options, **kwargs):
            return "Mês a mês"

        def selectbox(self, label, options, **kwargs):
            return "Todos" if label == "Pessoa" else "Total"

        def metric(self, *args, **kwargs):
            self.metrics.append((args, kwargs))
            if args and args[0] == "Variação":
                captured.append((args, kwargs))

        def markdown(self, *args, **kwargs):
            captured.append((args, kwargs))

        def caption(self, *args, **kwargs):
            pass

    columns_call = 0
    metric_cards = []

    def columns(spec):
        nonlocal columns_call
        columns_call += 1
        if spec == 4:
            return tuple(MetricCapture() for _ in range(4))
        if spec != 3:
            cards = (MetricCapture(), MetricCapture())
        else:
            cards = (MetricCapture(), MetricCapture(), MetricCapture())
            metric_cards.append(cards)
        return cards

    monkeypatch.setattr(ui_pages.st, "columns", columns)
    monkeypatch.setattr(ui_pages.st, "plotly_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui_pages, "_expense_table", lambda *args: None)
    monkeypatch.setattr(ui_pages.st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui_pages.st, "metric", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui_pages.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui_pages.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui_pages.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui_pages.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(ui_pages.st, "radio", lambda *args, **kwargs: "Mês a mês")
    monkeypatch.setattr(
        ui_pages.st,
        "selectbox",
        lambda label, options, **kwargs: "Todos" if label == "Pessoa" else "Total",
    )

    from streamline_finance.demo_data import make_demo_transactions
    from streamline_finance.ui_summary import PeriodComparison

    monkeypatch.setattr(ui_pages, "_mode", lambda: "demo")
    monkeypatch.setattr(ui_pages, "_transactions_for_mode", make_demo_transactions)
    monkeypatch.setattr(
        ui_pages,
        "compare_spending_periods",
        lambda *args, **kwargs: PeriodComparison(
            current_start=date(2026, 1, 1),
            current_end=date(2026, 1, 7),
            previous_start=date(2025, 12, 25),
            previous_end=date(2025, 12, 31),
            current_total_minor_units=800,
            previous_total_minor_units=1000,
            variation_minor_units=-200,
            variation_percent=-20.0,
        ),
    )
    ui_pages.render_analysis_page()
    assert "↓ −20.0%" in captured[-1][0][0]
    assert "#22C55E" in captured[-1][0][0]

    monkeypatch.setattr(
        ui_pages,
        "compare_spending_periods",
        lambda *args, **kwargs: PeriodComparison(
            current_start=date(2026, 1, 1),
            current_end=date(2026, 1, 7),
            previous_start=date(2025, 12, 25),
            previous_end=date(2025, 12, 31),
            current_total_minor_units=1200,
            previous_total_minor_units=1000,
            variation_minor_units=200,
            variation_percent=20.0,
        ),
    )
    ui_pages.render_analysis_page()
    assert "↑ +20.0%" in captured[-1][0][0]
    assert "#EF4444" in captured[-1][0][0]


def test_variation_card_explicitly_styles_signed_values_at_metric_scale(monkeypatch) -> None:
    import streamline_finance.ui_pages as ui_pages

    assert ui_pages._variation_card_presentation(-43.5) == (
        "↓ −43.5%",
        "#22C55E",
        "Queda de gastos no período comparado.",
    )
    assert ui_pages._variation_card_presentation(51.9) == (
        "↑ +51.9%",
        "#EF4444",
        "Aumento de gastos no período comparado.",
    )
    assert ui_pages._variation_card_presentation(None)[0] == "—"


def test_variation_card_value_uses_large_matching_metric_typography(monkeypatch) -> None:
    from streamline_finance.ui_pages import _render_variation_card

    captured = []

    class Card:
        def markdown(self, content, **kwargs):
            captured.append(content)

    _render_variation_card(Card(), -43.5)

    html = captured[0]
    assert "font-size:2.25rem" in html
    assert "↓ −43.5%" in html
    assert "#22C55E" in html


def test_uncategorized_expense_helper_obeys_date_and_person_filters():

    import streamline_finance.ui_pages as ui_pages
    from streamline_finance.demo_data import make_demo_transactions, review_demo_transaction

    rows = make_demo_transactions()
    rows = review_demo_transaction(
        rows,
        "demo-pending-01",
        movement_type=__import__(
            "streamline_finance.domain", fromlist=["MovementType"]
        ).MovementType.EXPENSE,
        macro="Needs",
        micro="Food",
    )
    target = next(row for row in rows if row.transaction_id == "demo-uncategorized-01")
    found = ui_pages.uncategorized_expenses(
        rows,
        start=target.occurred_on,
        end=target.occurred_on,
        person=target.person.value,
    )

    assert [row.transaction_id for row in found] == ["demo-uncategorized-01"]


def test_analysis_renders_top_period_comparison_and_category_review_button_in_demo(
    monkeypatch,
) -> None:
    import plotly.graph_objects as go

    import streamline_finance.ui_pages as ui_pages

    charts = []
    monkeypatch.setattr(ui_pages.st, "plotly_chart", lambda chart, **kwargs: charts.append(chart))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()

    assert not app.exception
    assert len(charts) == 2
    assert any(
        select.label == "Detalhar por" and select.value == "Total" for select in app.selectbox
    )
    assert len(app.dataframe) >= 1
    assert any(chart.layout.title.text == "Gasto líquido entre períodos iguais" for chart in charts)
    assert any(button.label == "Revisar transações sem categoria" for button in app.button)
    assert all(isinstance(chart, go.Figure) for chart in charts)
    assert any(button.label == "Revisar transações sem categoria" for button in app.button)


def test_uncategorized_review_button_is_hidden_if_no_uncategorized_expenses(monkeypatch) -> None:
    import streamline_finance.ui_pages as ui_pages

    rows = ui_pages._demo_transactions()
    reviewed_rows = []
    for row in rows:
        if row.movement_type is ui_pages.MovementType.PENDING:
            row = ui_pages.review_demo_transaction(
                (row,),
                row.transaction_id,
                movement_type=ui_pages.MovementType.EXPENSE,
                macro="Geral",
                micro="Revisado",
            )[0]
        elif row.movement_type is ui_pages.MovementType.EXPENSE and row.category is None:
            row = __import__("dataclasses").replace(
                row, category=ui_pages.Category("Geral", "Revisado")
            )
        reviewed_rows.append(row)
    reviewed = tuple(reviewed_rows)
    monkeypatch.setattr(ui_pages, "_demo_transactions", lambda: reviewed)
    monkeypatch.setattr(ui_pages.st, "altair_chart", lambda *args, **kwargs: None)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()

    assert not app.exception
    assert not any(button.label == "Revisar transações sem categoria" for button in app.button)
