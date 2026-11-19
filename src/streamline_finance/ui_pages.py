"""UI pages for the local app; all personal data access is explicit and server-side."""

from __future__ import annotations

import os
from datetime import date
from difflib import get_close_matches
from pathlib import Path

import httpx2 as httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from streamline_finance.categorization import (
    CategorizationRule,
    CategorizationStatus,
    suggest_description,
)
from streamline_finance.demo_data import (
    append_demo_import,
    make_demo_transactions,
    review_demo_transaction,
)
from streamline_finance.domain import Category, MovementType, Person, SourceKind, Transaction
from streamline_finance.importers.nubank import preview_nubank_csv
from streamline_finance.rules import HistoricalRuleError, load_expense_rules
from streamline_finance.storage import StoredTransaction
from streamline_finance.ui_summary import (
    PeriodComparison,
    SpendingTrendPoint,
    build_spending_trend,
    category_highlights,
    compare_spending_periods,
    format_brl,
    top_expenses,
)

DEFAULT_API_URL = "http://127.0.0.1:8000"
HISTORICAL_WORKBOOK_CANDIDATES = (
    Path("data/historical/ControleFinanceiro_VR.xlsx"),
    Path("data/historical/ControleFinanceiro_VR-2.xlsx"),
    Path("data/reference/ControleFinanceiro.xlsx"),
)


def _mode() -> str:
    return st.session_state.get("data_mode", "demo")


def _person_map() -> dict[str, Person]:
    return {
        "Iury": Person.SELF,
        "Ana Clara": Person.SPOUSE,
        "Compartilhado": Person.SHARED,
    }


def _person_label(person: str) -> str:
    return {"self": "Iury", "spouse": "Ana Clara", "shared": "Compartilhado"}.get(
        person, "Desconhecido"
    )


def _demo_transactions() -> tuple[Transaction, ...]:
    if "demo_transactions" not in st.session_state:
        st.session_state["demo_transactions"] = make_demo_transactions()
    return st.session_state["demo_transactions"]


def _api_url() -> str:
    return os.environ.get("STREAMLIT_FINANCE_API_URL", DEFAULT_API_URL).rstrip("/")


def _api_get(path: str, **params):
    try:
        return httpx.get(f"{_api_url()}{path}", params=params, timeout=2.0)
    except httpx.HTTPError:
        return None


def _api_post(path: str, *, data=None, files=None, json=None):
    try:
        return httpx.post(f"{_api_url()}{path}", data=data, files=files, json=json, timeout=20.0)
    except httpx.HTTPError:
        return None


def _api_offline_message() -> None:
    st.error(
        "Não conectei à API local. Inicie outro terminal com "
        "`uv run uvicorn streamline_finance.api:app --host 127.0.0.1 --port 8000`."
    )


def _real_transactions() -> tuple[StoredTransaction, ...] | None:
    response = _api_get("/transactions")
    if response is None:
        _api_offline_message()
        return None
    if response.status_code != 200:
        st.error("Não consegui ler os dados locais. Confira a API e tente novamente.")
        return None
    transactions: list[StoredTransaction] = []
    for row in response.json()["transactions"]:
        category = (
            Category(row["category"]["macro"], row["category"]["micro"])
            if row["category"]
            else None
        )
        transactions.append(
            StoredTransaction(
                transaction_id=row["transaction_id"],
                source_key=row["source_key"],
                description=row["description"],
                amount_minor_units=row["amount_minor_units"],
                currency=row["currency"],
                movement_type=MovementType(row["movement_type"]),
                person=Person(row["person"]),
                occurred_on=date.fromisoformat(row["occurred_on"]),
                posted_on=date.fromisoformat(row["posted_on"]) if row["posted_on"] else None,
                category=category,
                source_kind=SourceKind(row["source_kind"]),
            )
        )
    return tuple(transactions)


def _transactions_for_mode() -> tuple[StoredTransaction, ...] | tuple[Transaction, ...] | None:
    if _mode() == "demo":
        return _demo_transactions()
    return _real_transactions()


def render_analysis_page() -> None:
    st.title("Análise de gastos")
    if _mode() == "demo":
        st.warning("Modo Demo: dados inteiramente fictícios; alterações ficam só nesta sessão.")

    transactions = _transactions_for_mode()
    if transactions is None:
        return

    today = date.today()
    default_start = date(today.year, today.month, 1) if today.month > 1 else date(today.year, 1, 1)
    date_col, person_col = st.columns([2, 1])
    selected_dates = date_col.date_input(
        "  Período",
        value=(default_start, today),
        key="analysis_date_range",
    )
    person_choice = person_col.selectbox(
        "Pessoa",
        ("Todos", "Iury", "Ana Clara", "Compartilhado"),
        key="analysis_person",
    )
    if not isinstance(selected_dates, tuple) or len(selected_dates) != 2:
        st.info("Escolha as duas datas do período para mostrar a análise.")
        return
    start, end = selected_dates
    if start > end:
        st.error("A data inicial precisa ser anterior à data final.")
        return
    filtered = tuple(
        row
        for row in transactions
        if person_choice == "Todos" or row.person is _person_map()[person_choice]
    )

    summary_mode = "demo" if _mode() == "demo" else "real"
    st.subheader(
        "💸 Gasto líquido do período",
        help="Despesas confirmadas menos estornos no intervalo e pessoa escolhidos.",
    )
    total_points = build_spending_trend(
        filtered,
        start=start,
        end=end,
        granularity="month",
        dimension="total",
    )
    total_minor = sum(point.amount_minor_units for point in total_points)
    largest_category, largest_amount, best_category, previous_amount, current_amount = (
        category_highlights(filtered, start=start, end=end)
    )
    all_expenses = top_expenses(filtered, start=start, end=end, limit=None)
    cards = st.columns(4)
    cards[0].metric("Gastos confirmados", format_brl(total_minor))
    cards[1].metric(
        "Maior microcategoria",
        format_brl(largest_amount) if largest_category else "—",
        help=" / ".join(largest_category) if largest_category else "Sem categoria no período",
    )
    if largest_category:
        cards[1].caption(" / ".join(largest_category))
    cards[2].metric(
        "Maior economia", format_brl(previous_amount - current_amount) if best_category else "—"
    )
    if best_category:
        cards[2].caption(
            f"{' / '.join(best_category)}: {format_brl(previous_amount)} → "
            f"{format_brl(current_amount)}"
        )
    else:
        cards[2].caption("Nenhuma redução no período")
    cards[3].metric(
        "Maior despesa", format_brl(all_expenses[0].amount_minor_units) if all_expenses else "—"
    )
    if all_expenses:
        cards[3].caption(_split_description(all_expenses[0].description)[1])

    control_col, dimension_col = st.columns(2)
    granularity_label = control_col.radio(
        "Ver por período",
        ("Mês a mês", "Semana a semana", "Dia a dia"),
        horizontal=True,
        key="analysis_granularity",
    )
    granularity = {
        "Mês a mês": "month",
        "Semana a semana": "week",
        "Dia a dia": "day",
    }[granularity_label]
    dimension_label = dimension_col.selectbox(
        "Detalhar por",
        ("Total", "Pessoa", "Macrocategoria", "Microcategoria"),
        key="analysis_dimension",
    )
    dimension = {
        "Total": "total",
        "Pessoa": "person",
        "Macrocategoria": "macro",
        "Microcategoria": "micro",
    }[dimension_label]
    trend = build_spending_trend(
        filtered,
        start=start,
        end=end,
        granularity=granularity,
        dimension=dimension,
    )

    if not trend:
        st.info("Nenhum gasto confirmado neste período e filtro.")
    else:
        chart = _trend_chart(trend, granularity, dimension)
        st.plotly_chart(chart, width="stretch", config={"scrollZoom": False, "displaylogo": False})
        if dimension == "person":
            st.caption("Selecione uma pessoa no filtro para isolar seus gastos.")
        elif dimension in {"macro", "micro"}:
            st.caption("O gráfico mostra uma dimensão por vez para manter a leitura clara.")

    st.subheader(
        "📋 Maiores gastos no período",
        help=("Transações individuais no intervalo/pessoa selecionados. Estornos não entram."),
    )
    if all_expenses:
        _expense_table(all_expenses, start, end)
    else:
        st.info("Nenhum gasto individual no período selecionado.")

    st.subheader(
        "↔️ Comparação com o período anterior",
        help=(
            "Compara os mesmos filtros contra os dias imediatamente anteriores, "
            "em intervalo de igual duração."
        ),
    )
    person_code = _person_map()[person_choice].value if person_choice != "Todos" else None
    comparison = compare_spending_periods(filtered, start=start, end=end, person=person_code)
    comparison_col1, comparison_col2, comparison_col3 = st.columns(3)
    comparison_col1.metric(
        f"Selecionado ({start.isoformat()} — {end.isoformat()})",
        format_brl(comparison.current_total_minor_units),
    )
    comparison_col2.metric(
        "Anterior "
        f"({comparison.previous_start.isoformat()} — {comparison.previous_end.isoformat()})",
        format_brl(comparison.previous_total_minor_units),
    )
    _render_variation_card(comparison_col3, comparison.variation_percent)
    st.plotly_chart(
        _period_comparison_chart(comparison), width="stretch", config={"displaylogo": False}
    )

    if _mode() == "demo":
        missing_count = len(
            uncategorized_expenses(filtered, start=start, end=end, person=person_code)
        )
    else:
        missing_response = _api_get(
            "/transactions/uncategorized",
            start=start.isoformat(),
            end=end.isoformat(),
            person=person_code,
        )
        missing_count = (
            missing_response.json()["count"]
            if missing_response is not None and missing_response.status_code == 200
            else 0
        )
    if missing_count:
        st.warning(f"Há {missing_count} despesa(s) sem categoria neste período.")
        if st.button("Revisar transações sem categoria", key="jump-to-review"):
            if _mode() == "demo":
                st.session_state["review_uncategorized_only"] = True
            st.switch_page("pages/3_Revisar.py")
    st.caption(
        f"Fonte de dados: {'demonstração fictícia' if summary_mode == 'demo' else 'SQLite local'}."
    )


def uncategorized_expenses(
    transactions,
    *,
    start: date,
    end: date,
    person: str | None = None,
) -> tuple:
    return tuple(
        row
        for row in transactions
        if row.movement_type is MovementType.EXPENSE
        and row.category is None
        and start <= row.occurred_on <= end
        and (person is None or row.person.value == person)
    )


def _period_comparison_chart(comparison: PeriodComparison) -> go.Figure:
    values = [comparison.previous_total_minor_units, comparison.current_total_minor_units]
    labels = [format_brl(value) for value in values]
    figure = go.Figure(
        go.Bar(
            x=["Anterior", "Selecionado"],
            y=[v / 100 for v in values],
            text=labels,
            customdata=labels,
            textposition="outside",
            marker_color="#4F8BF9",
            hovertemplate="%{x}<br>%{customdata}<extra></extra>",
        )
    )
    figure.update_layout(
        title="Gasto líquido entre períodos iguais",
        height=300,
        separators=",.",
        yaxis_title="Gasto líquido (R$)",
        yaxis_rangemode="tozero",
    )
    figure.update_yaxes(tickprefix="R$ ", tickformat=",.2f")
    return figure


def _top_expense_rows(expenses) -> list[dict[str, str]]:
    rows = []
    for item in expenses:
        get = item.get if isinstance(item, dict) else lambda key: getattr(item, key)
        occurred_on = get("occurred_on")
        payment, description = _split_description(get("description"))
        rows.append(
            {
                "Data": occurred_on.isoformat()
                if hasattr(occurred_on, "isoformat")
                else occurred_on,
                "Tipo de pagamento": payment,
                "Descrição": description,
                "Pessoa": _person_label(get("person")),
                "Macro": get("category_macro"),
                "Micro": get("category_micro"),
                "Valor": format_brl(get("amount_minor_units")),
            }
        )
    return rows


def _split_description(description: str) -> tuple[str, str]:
    payment, separator, detail = description.partition(" - ")
    return (
        (payment.strip(), detail.strip())
        if separator and detail.strip()
        else ("Não informado", description)
    )


def _expense_table(expenses, start: date, end: date) -> None:
    rows = _top_expense_rows(expenses)
    frame = pd.DataFrame(rows)
    frame["_centavos"] = [item.amount_minor_units for item in expenses]
    if st.session_state.get("expense_date_bounds") != (start, end):
        st.session_state.pop("expense_dates", None)
        st.session_state["expense_date_bounds"] = (start, end)
    with st.expander("Filtrar despesas"):
        dates = st.date_input(
            "Data da despesa",
            value=(start, end),
            min_value=start,
            max_value=end,
            key="expense_dates",
        )
        text = st.text_input("Buscar descrição", key="expense_description")
        selections = {
            column: st.multiselect(
                column, sorted(frame[column].unique()), key=f"expense-filter-{column}"
            )
            for column in ("Tipo de pagamento", "Pessoa", "Macro", "Micro")
        }
        minimum = st.number_input(
            "Valor mínimo (R$)", min_value=0.0, value=0.0, step=1.0, key="expense_min"
        )
        maximum = st.number_input(
            "Valor máximo (R$; 0 = sem limite)",
            min_value=0.0,
            value=0.0,
            step=1.0,
            key="expense_max",
        )
    if isinstance(dates, tuple) and len(dates) == 2:
        frame = frame[frame["Data"].between(dates[0].isoformat(), dates[1].isoformat())]
    if text:
        frame = frame[frame["Descrição"].str.contains(text, case=False, regex=False)]
    for column, selected in selections.items():
        if selected:
            frame = frame[frame[column].isin(selected)]
    from decimal import Decimal

    frame = frame[frame["_centavos"] >= int(Decimal(str(minimum)) * 100)]
    if maximum:
        frame = frame[frame["_centavos"] <= int(Decimal(str(maximum)) * 100)]
    st.caption(f"{len(frame)} despesa(s) encontrada(s).")
    st.dataframe(frame.drop(columns="_centavos"), width="stretch", hide_index=True)


def _variation_card_presentation(
    variation_percent: float | None,
) -> tuple[str, str, str]:
    if variation_percent is None:
        return (
            "—",
            "#9CA3AF",
            "Variação não calculável quando o período anterior não teve gasto.",
        )
    if variation_percent < 0:
        return (
            f"↓ −{abs(variation_percent):.1f}%",
            "#22C55E",
            "Queda de gastos no período comparado.",
        )
    if variation_percent > 0:
        return (
            f"↑ +{variation_percent:.1f}%",
            "#EF4444",
            "Aumento de gastos no período comparado.",
        )
    return "→ 0.0%", "#9CA3AF", "Gastos sem variação entre os períodos."


def _render_variation_card(card, variation_percent: float | None) -> None:
    """Render signed change with metric-sized text and explicit semantic color."""
    label, color, help_text = _variation_card_presentation(variation_percent)

    card.markdown(
        "<div style='min-height: 82px;'>"
        f"<div title='{help_text}' style='font-size:0.875rem; opacity:0.75; margin-bottom:0.4rem;'>"
        "Variação <span aria-hidden='true'>ⓘ</span></div>"
        f"<div style='font-size:2.25rem; line-height:1.2; font-weight:600; color:{color};'>"
        f"{label}</div></div>",
        unsafe_allow_html=True,
    )


def _trend_chart(
    points: tuple[SpendingTrendPoint, ...],
    granularity: str,
    dimension: str,
) -> go.Figure:
    figure = go.Figure()
    for group in sorted({point.group for point in points}):
        series = [point for point in points if point.group == group]
        figure.add_scatter(
            x=[
                point.period + "-01" if granularity == "month" else point.period for point in series
            ],
            y=[point.amount_minor_units / 100 for point in series],
            customdata=[format_brl(point.amount_minor_units) for point in series],
            name=_person_label(group) if dimension == "person" else group,
            mode="lines+markers",
            hovertemplate="%{x|%d/%m/%Y}<br>%{customdata}<extra>%{fullData.name}</extra>",
        )
    figure.update_layout(
        height=380, separators=",.", yaxis_title="Gasto líquido (R$)", hovermode="closest"
    )
    figure.update_yaxes(tickprefix="R$ ", tickformat=",.2f")
    return figure


def render_import_page() -> None:
    st.title("Importar extrato")
    if _mode() == "demo":
        st.warning("Demo Sandbox: ações alteram somente dados fictícios em memória.")
        _render_demo_import()
        return
    _render_real_import()


def _render_demo_import() -> None:
    st.caption("Envie um CSV fictício. Prévia e confirmação ficam apenas nesta sessão Demo.")
    person_label = st.selectbox("Pessoa do exemplo", tuple(_person_map()))
    uploaded = st.file_uploader("CSV sintético", type=["csv"], key="demo_csv_upload")
    if uploaded is not None and st.button("Gerar prévia fictícia"):
        response = _api_post(
            "/imports/preview",
            data={
                "source_key": "demo-upload",
                "person": _person_map()[person_label].value,
                "source_kind": SourceKind.BANK_ACCOUNT.value,
            },
            files={"file": (uploaded.name, uploaded.getvalue(), "text/csv")},
        )
        if response is None:
            _api_offline_message()
            return
        if response.status_code != 200:
            _show_api_error(response)
            return
        st.session_state["demo_upload_preview"] = {
            "content": uploaded.getvalue(),
            "person": _person_map()[person_label],
            "response": response.json(),
        }

    preview = st.session_state.get("demo_upload_preview")
    if preview is None:
        return
    payload = preview["response"]
    st.write(f"Prévia: {payload['transaction_count']} linha(s) sintéticas.")
    if payload["errors"]:
        for error in payload["errors"]:
            st.write(_safe_error(error))
        return
    st.dataframe(
        [
            {
                "Data": row["occurred_on"],
                "Descrição": row["description"],
                "Valor": format_brl(row["amount_minor_units"]),
                "Natureza": "Pendente",
            }
            for row in payload["transactions"]
        ],
        width="stretch",
        hide_index=True,
    )
    if payload["can_confirm"] and st.button("Adicionar ao Demo Sandbox em memória"):
        sandbox_preview = preview_nubank_csv(
            preview["content"],
            person=preview["person"],
            source_key="demo-generated",
        )
        st.session_state["demo_transactions"] = append_demo_import(
            _demo_transactions(), sandbox_preview.transactions
        )
        st.session_state.pop("demo_upload_preview", None)
        st.success(
            "Movimentações adicionadas somente à sessão. Nada foi gravado no banco ou em disco."
        )
        st.rerun()


def _render_real_import() -> None:
    st.caption("Faça uma prévia primeiro. Nada será salvo até você confirmar.")
    format_label = st.selectbox(
        "Formato do arquivo", ("Extrato Nubank", "Fatura C6", "Fatura Nubank")
    )
    import_format = {
        "Extrato Nubank": "nubank_statement",
        "Fatura C6": "c6_invoice",
        "Fatura Nubank": "nubank_invoice",
    }[format_label]
    invoice_month = None
    if import_format != "nubank_statement":
        invoice_date = st.date_input(
            "Competência da fatura (selecione qualquer dia do mês)",
            value=date.today(),
            key="invoice_month",
        )
        invoice_month = invoice_date.strftime("%Y-%m")
        st.info(
            "Confira a competência; parcelas originais são preservadas sem interpretação. "
            "Todos os lançamentos exigem revisão."
        )
        st.warning(
            "A conciliação com pagamento de fatura ainda não está implementada. "
            "Se o pagamento no extrato foi confirmado como despesa, o gasto pode ficar duplicado."
        )
    person_label = st.selectbox("Pessoa dona do extrato", tuple(_person_map()))
    source_key = st.text_input(
        "Identificação da conta/origem", placeholder="Ex.: nubank-conta-iury"
    )
    source_mapping_ack = st.checkbox(
        "Confirmei que essa identificação corresponde à conta ou cartão escolhido.",
        key="source_mapping_ack",
    )
    source_kind_label = st.selectbox("Tipo da origem", ("Conta bancária", "Cartão de crédito"))
    uploaded = st.file_uploader("Arquivo CSV", type=["csv"])
    rules = _review_rules()
    person = _person_map()[person_label].value
    source_kind = {
        "Conta bancária": SourceKind.BANK_ACCOUNT.value,
        "Cartão de crédito": SourceKind.CREDIT_CARD.value,
    }[source_kind_label]
    if import_format != "nubank_statement" and source_kind != SourceKind.CREDIT_CARD.value:
        st.warning("Selecione Cartão de crédito como tipo da origem para importar uma fatura.")
        return

    if st.button(
        "Gerar prévia",
        disabled=uploaded is None or not source_key.strip() or not source_mapping_ack,
    ):
        if uploaded is None:
            st.warning("Escolha um CSV antes de continuar.")
            return
        content = uploaded.getvalue()
        response = _api_post(
            "/imports/preview",
            data={
                "source_key": source_key.strip(),
                "person": person,
                "source_kind": source_kind,
                "import_format": import_format,
                **({"invoice_month": invoice_month} if invoice_month else {}),
            },
            files={"file": (uploaded.name, content, "text/csv")},
        )
        if response is None:
            _api_offline_message()
            return
        if response.status_code != 200:
            _show_api_error(response)
            return
        st.session_state["import_preview"] = {
            "content": content,
            "filename": uploaded.name,
            "source_key": source_key.strip(),
            "person": person,
            "source_kind": source_kind,
            "import_format": import_format,
            "invoice_month": invoice_month,
            "response": response.json(),
        }

    preview = st.session_state.get("import_preview")
    if not preview:
        return
    if (
        preview["source_key"] != source_key.strip()
        or preview["person"] != person
        or preview["source_kind"] != source_kind
        or preview.get("import_format", "nubank_statement") != import_format
        or preview.get("invoice_month") != invoice_month
    ):
        st.warning("A prévia aberta usa escolhas diferentes. Gere outra prévia antes de confirmar.")
        return
    _render_preview_and_confirmation(preview, rules)


def _render_preview_and_confirmation(preview: dict, rules: list[CategorizationRule]) -> None:
    payload = preview["response"]
    st.subheader("Prévia antes de salvar")
    st.write(f"Linhas válidas: {payload['transaction_count']}")
    if payload["errors"]:
        st.error("Há erros. Corrija o arquivo na origem e gere nova prévia.")
        for error in payload["errors"]:
            st.write(_safe_error(error))
        return
    if payload["transactions"]:
        st.dataframe(
            [
                {
                    "Data": row["occurred_on"],
                    "Descrição": row["description"],
                    "Valor": format_brl(row["amount_minor_units"]),
                    "Natureza": "Pendente de revisão",
                    "Categoria sugerida (se despesa)": _suggestion_label(row["description"], rules),
                    "Pessoa": _person_label(row["person"]),
                }
                for row in payload["transactions"]
            ],
            width="stretch",
            hide_index=True,
        )
        with st.expander("Colunas originais — revise antes de confirmar"):
            for index, row in enumerate(payload["transactions"], start=1):
                st.write(f"Linha {index}")
                source_fields = row["source_fields"]
                st.json(
                    source_fields
                    if preview.get("invoice_month")
                    else {
                        "Data": source_fields.get("Data", row["occurred_on"]),
                        "Valor": format_brl(row["amount_minor_units"]),
                        "Identificador": row["transaction_id"],
                        "Descrição": row["description"],
                    }
                )
    if not payload["can_confirm"]:
        st.warning("Confirmação indisponível até corrigir todas as linhas inválidas.")
        return
    confirm_ack = st.checkbox(
        "Revisei as linhas acima e quero salvar esta importação.",
        key="confirm_import_ack",
    )
    if confirm_ack and st.button("Confirmar importação", key="confirm-import"):
        response = _api_post(
            "/imports/confirm",
            data={
                "source_key": preview["source_key"],
                "person": preview["person"],
                "source_kind": preview["source_kind"],
                "confirmed": "true",
                "import_format": preview.get("import_format", "nubank_statement"),
                **(
                    {"invoice_month": preview["invoice_month"]}
                    if preview.get("invoice_month")
                    else {}
                ),
            },
            files={"file": (preview["filename"], preview["content"], "text/csv")},
        )
        if response is None:
            _api_offline_message()
            return
        if response.status_code not in (200, 201):
            _show_api_error(response)
            return
        result = response.json()
        st.success(
            f"Importação concluída. Novos movimentos: {result['imported_count']}; "
            f"já existentes: {result['duplicate_count']}."
        )
        st.session_state.pop("import_preview", None)
        st.session_state.pop("confirm_import_ack", None)


def render_review_page() -> None:
    st.title("Revisar movimentações")
    if _mode() == "demo":
        st.warning(
            "Demo Sandbox: classificações ficam na sessão e desaparecem ao sair do modo Demo."
        )
        _render_demo_review_controls()
        return
    _render_real_review()


def _render_demo_review_controls() -> None:
    transactions = _demo_transactions()
    categories = {row.category for row in transactions if row.category is not None}
    categories.update(st.session_state.get("demo_categories", []))
    _category_management(categories, demo=True)
    pending = [row for row in transactions if row.movement_type is MovementType.PENDING]
    only_uncategorized = st.session_state.pop("review_uncategorized_only", False)
    if only_uncategorized:
        pending = [
            row
            for row in transactions
            if row.movement_type is MovementType.EXPENSE and row.category is None
        ]
    if not pending:
        st.info("Não há movimentações sintéticas para revisar.")
        return
    row = st.selectbox(
        "Movimentação fictícia" if _mode() == "demo" else "Despesa sem categoria",
        pending,
        format_func=lambda item: (
            f"{item.occurred_on} · {item.description} · {format_brl(item.amount.minor_units)}"
        ),
        key="demo_pending_transaction",
    )
    kind_label = st.selectbox("Natureza confirmada", ("Despesa", "Entrada", "Transferência"))
    macro = micro = None
    if kind_label == "Despesa":
        macro, micro = _category_selectors(categories, "demo")
    if st.button("Aplicar somente nesta demonstração"):
        movement_type = {
            "Despesa": MovementType.EXPENSE,
            "Entrada": MovementType.INCOME,
            "Transferência": MovementType.TRANSFER,
        }[kind_label]
        try:
            st.session_state["demo_transactions"] = review_demo_transaction(
                transactions,
                row.transaction_id,
                movement_type=movement_type,
                macro=macro,
                micro=micro,
            )
        except ValueError as error:
            st.error(str(error))
            return
        st.success("Alteração aplicada somente à demonstração em memória.")
        st.rerun()


def _render_real_review() -> None:
    only_uncategorized = st.session_state.pop("review_uncategorized_only", False)
    st.header(
        "Revisar despesas sem categoria" if only_uncategorized else "Revisar movimentos pendentes"
    )
    historical_rules = _review_rules()
    categories = st.session_state.get("review_categories", set())
    _category_management(categories, demo=False)
    response = _api_get(
        "/transactions",
        **({} if only_uncategorized else {"movement_type": "pending"}),
        **({"uncategorized_only": "true"} if only_uncategorized else {}),
    )
    if response is None:
        _api_offline_message()
        return
    if response.status_code != 200:
        st.error("Não foi possível carregar movimentos para revisão.")
        return
    rows = response.json()["transactions"]
    if not rows:
        st.info("Nenhum movimento pendente para revisão.")
        return

    for row in rows:
        with st.expander(f"{row['occurred_on']} · {row['description']} · {row['source_key']}"):
            st.write(f"Valor: {format_brl(row['amount_minor_units'])}")
            st.write(f"Pessoa: {_person_label(row['person'])}")
            movement_label = st.selectbox(
                "Natureza confirmada",
                ("Despesa",) if only_uncategorized else ("Despesa", "Entrada", "Transferência"),
                key=f"movement-{row['source_key']}-{row['transaction_id']}",
            )
            movement_type = {
                "Despesa": "expense",
                "Entrada": "income",
                "Transferência": "transfer",
            }[movement_label]
            result = suggest_description(row["description"], historical_rules)
            suggested = result.suggested_category if movement_type == "expense" else None
            if movement_type == "expense" and result.status is CategorizationStatus.AMBIGUOUS:
                st.warning(
                    "Históricos discordam sobre esta descrição; escolha a categoria manualmente."
                )
            if suggested:
                st.info(
                    f"Sugestão: {_suggestion_label(row['description'], historical_rules)}. "
                    "Confira antes de salvar."
                )
                macro_key = f"macro-{row['source_key']}-{row['transaction_id']}"
                micro_key = f"micro-{row['source_key']}-{row['transaction_id']}"
                if st.button(
                    "Usar sugestão",
                    key=f"use-suggestion-{row['source_key']}-{row['transaction_id']}",
                ):
                    st.session_state[macro_key] = suggested.macro
                    st.session_state[micro_key] = suggested.micro
            macro = micro = None
            if movement_type == "expense":
                macro, micro = _category_selectors(
                    categories, f"{row['source_key']}-{row['transaction_id']}"
                )
            if st.button(
                "Confirmar natureza e categoria",
                key=f"confirm-type-{row['source_key']}-{row['transaction_id']}",
            ):
                if movement_type == "expense" and (not macro or not micro):
                    st.warning("Informe macro e micro categoria para confirmar um gasto.")
                    return
                path = f"/transactions/{row['source_key']}/{row['transaction_id']}"
                if only_uncategorized:
                    response = _api_post(
                        f"{path}/category", json={"confirmed": True, "macro": macro, "micro": micro}
                    )
                else:
                    response = _api_post(
                        f"{path}/movement-type",
                        json={
                            "movement_type": movement_type,
                            "confirmed": True,
                            "macro": macro,
                            "micro": micro,
                        },
                    )
                _show_action_result(response, "Natureza salva.")


def _review_rules() -> list[CategorizationRule]:
    response = _api_get("/transactions", movement_type="expense")
    rules = []
    if response is None or response.status_code != 200:
        st.warning("Histórico da aplicação indisponível; sugestões desativadas.")
        return []
    else:
        rules = [
            CategorizationRule("app-history", row["description"], Category(**row["category"]))
            for row in response.json()["transactions"]
            if row["category"] is not None
        ]
    catalog_response = _api_get("/categories")
    categories = {
        Category(**row["category"]) for row in response.json()["transactions"] if row["category"]
    }
    if catalog_response is not None and catalog_response.status_code == 200:
        categories.update(Category(**row) for row in catalog_response.json()["categories"])
    st.session_state["review_categories"] = categories
    mapping_confirmed = st.checkbox(
        "Confirmo o mapeamento provisório: Tipo de Fluxo = macro, Fluxo = micro, "
        "Classificação = natureza; Observação contém a descrição para regra exata.",
        key="confirm_category_mapping",
    )
    workbook_path = _historical_workbook_path()
    if mapping_confirmed and workbook_path is None:
        st.warning(
            "Mapeamento confirmado, mas a planilha não está nos locais conhecidos "
            "data/historical/ ou data/reference/. Nenhum outro local será procurado."
        )
        return []
    elif mapping_confirmed and workbook_path is not None:
        try:
            loaded = load_expense_rules(
                workbook_path.read_bytes(),
                confirm_column_mapping=True,
            )
            categories.update(loaded.categories)
            excluded = set(loaded.excluded_descriptions)
            rules = [
                rule
                for rule in rules
                if " ".join(rule.description.casefold().split()) not in excluded
            ]
            rules.extend(loaded.rules)
            st.caption(f"Regras locais carregadas para esta sessão: {loaded.rule_count}.")
            if excluded:
                st.warning(
                    f"{len(excluded)} descrição(ões) com categoria incompleta ou conflitante "
                    "ficaram sem sugestão e precisam de revisão manual."
                )
                with st.expander("Linhas da planilha para revisar"):
                    st.dataframe(
                        [
                            {"Aba": "Entrada", "Linha": row, "Motivo": reason}
                            for row, reason in loaded.issue_rows
                        ],
                        hide_index=True,
                    )
            if loaded.skipped_without_description:
                st.caption(
                    f"{loaded.skipped_without_description} linha(s) sem descrição foram ignoradas."
                )
        except HistoricalRuleError as error:
            st.error(f"Planilha não carregada ({error.code}): {error.message}")
            return []
    return rules


def _category_selectors(categories: set[Category], key: str) -> tuple[str | None, str | None]:
    macros = sorted({category.macro for category in categories})
    macro = st.selectbox(
        "Macro categoria", macros, index=None, placeholder="Selecione", key=f"macro-{key}"
    )
    micros = sorted({category.micro for category in categories if category.macro == macro})
    micro = st.selectbox(
        "Micro categoria", micros, index=None, placeholder="Selecione", key=f"micro-{key}"
    )
    return macro, micro


def _category_management(categories: set[Category], *, demo: bool) -> None:
    with st.expander("Cadastrar categoria"):
        macro = st.text_input("Nova macrocategoria", key="new-category-macro")
        micro = st.text_input("Nova microcategoria", key="new-category-micro")

        def normalize(value):
            return " ".join(value.split()).casefold()

        macro, micro = " ".join(macro.split()), " ".join(micro.split())
        exact = any(
            normalize(c.macro) == normalize(macro) and normalize(c.micro) == normalize(micro)
            for c in categories
        )
        names = sorted({c.macro for c in categories} | {c.micro for c in categories})
        similar = (
            sorted(
                set(
                    get_close_matches(macro, names, cutoff=0.8)
                    + get_close_matches(micro, names, cutoff=0.8)
                )
            )
            if macro and micro
            else []
        )
        if exact:
            st.warning("Essa categoria já existe.")
        if similar and not exact:
            st.warning("Nomes parecidos já existentes: " + ", ".join(similar))
        confirmed = st.checkbox("Confirmo o cadastro da categoria", key="new-category-confirm")
        if st.button("Cadastrar", disabled=not macro or not micro or exact or not confirmed):
            if demo:
                st.session_state.setdefault("demo_categories", []).append(Category(macro, micro))
                st.rerun()
            else:
                response = _api_post(
                    "/categories", json={"macro": macro, "micro": micro, "confirmed": True}
                )
                _show_action_result(response, "Categoria cadastrada.")


def _historical_workbook_path() -> Path | None:
    return next((path.resolve() for path in HISTORICAL_WORKBOOK_CANDIDATES if path.is_file()), None)


def _suggestion_label(description: str, rules: list[CategorizationRule]) -> str:
    result = suggest_description(description, rules)
    if result.status is CategorizationStatus.AMBIGUOUS:
        return "Conflito — revisar"
    if result.suggested_category is None:
        return "Sem sugestão"
    sources = []
    if "app-history" in result.matched_rule_ids:
        sources.append("aplicação")
    if any(rule_id.startswith("history-") for rule_id in result.matched_rule_ids):
        sources.append("planilha")
    category = result.suggested_category
    return f"{category.macro} / {category.micro} ({' e '.join(sources)})"


def _show_action_result(response, success_message: str) -> None:
    if response is None:
        _api_offline_message()
    elif response.status_code == 200:
        st.success(success_message)
        st.rerun()
    else:
        _show_api_error(response)


def _show_api_error(response) -> None:
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("detail") if isinstance(body, dict) else None
    st.error(str(detail) if detail else f"Pedido não concluído (HTTP {response.status_code}).")


def _safe_error(error: dict[str, object]) -> str:
    line = error.get("line_number")
    suffix = f" — linha {line}" if line is not None else ""
    return f"{error.get('message', 'Erro de validação')}{suffix}"


def _person_label(person: str) -> str:
    return {"self": "Iury", "spouse": "Ana Clara", "shared": "Compartilhado"}.get(
        person, "Desconhecido"
    )
