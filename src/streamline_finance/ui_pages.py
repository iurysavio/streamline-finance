"""UI pages for the local app; all personal data access is explicit and server-side."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import altair as alt
import httpx2 as httpx
import pandas as pd
import streamlit as st

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
    compare_spending_periods,
    format_brl,
    top_expenses,
)

DEFAULT_API_URL = "http://127.0.0.1:8000"
HISTORICAL_WORKBOOK_CANDIDATES = (
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
    default_start = (
        date(today.year - 1, today.month, 1) if today.month > 1 else date(today.year - 1, 1, 1)
    )
    date_col, person_col = st.columns([2, 1])
    selected_dates = date_col.date_input(
        "Período",
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
    st.metric("Gastos confirmados", format_brl(total_minor))

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
        st.altair_chart(chart, width="stretch", theme="streamlit")
        if dimension == "person":
            st.caption("Selecione uma pessoa no filtro para isolar seus gastos.")
        elif dimension in {"macro", "micro"}:
            st.caption("O gráfico mostra uma dimensão por vez para manter a leitura clara.")

    st.subheader(
        "📋 Maiores gastos no período",
        help=(
            "Dez maiores transações individuais no intervalo/pessoa selecionados. "
            "Estornos não entram."
        ),
    )
    if _mode() == "demo":
        expenses = top_expenses(
            filtered,
            start=start,
            end=end,
            person=_person_map()[person_choice].value if person_choice != "Todos" else None,
            limit=10,
        )
    else:
        top_response = _api_get(
            "/reports/top-expenses",
            start=start.isoformat(),
            end=end.isoformat(),
            person=_person_map()[person_choice].value if person_choice != "Todos" else None,
            limit=10,
        )
        expenses = (
            top_response.json()["expenses"]
            if top_response is not None and top_response.status_code == 200
            else ()
        )
    if expenses:
        st.dataframe(
            _top_expense_rows(expenses),
            width="stretch",
            hide_index=True,
        )
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
    st.altair_chart(
        _period_comparison_chart(comparison).properties(
            title="Gasto líquido entre períodos iguais"
        ),
        width="stretch",
        theme="streamlit",
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


def _period_comparison_chart(comparison: PeriodComparison) -> alt.Chart:
    frame = pd.DataFrame(
        [
            {
                "Período": "Anterior",
                "Valor centavos": comparison.previous_total_minor_units,
                "Rótulo": format_brl(comparison.previous_total_minor_units),
            },
            {
                "Período": "Selecionado",
                "Valor centavos": comparison.current_total_minor_units,
                "Rótulo": format_brl(comparison.current_total_minor_units),
            },
        ]
    )
    bars = (
        alt.Chart(frame)
        .mark_bar(
            cornerRadiusTopLeft=5,
            cornerRadiusTopRight=5,
            color="#4F8BF9",
            opacity=0.95,
        )
        .encode(
            x=alt.X("Período:N", title=None),
            y=alt.Y(
                "Valor centavos:Q",
                title="Gasto líquido (R$)",
                scale=alt.Scale(domainMin=0),
                axis=alt.Axis(labelExpr="'R$ ' + format(datum.value / 100, ',.2f')"),
            ),
            tooltip=[alt.Tooltip("Período:N"), alt.Tooltip("Rótulo:N", title="Valor")],
        )
    )
    labels = (
        alt.Chart(frame)
        .mark_text(
            dy=-10,
            fontWeight="bold",
            color="#F8FAFC",
            fontSize=14,
            stroke="#111827",
            strokeWidth=0.25,
        )
        .encode(
            x=alt.X("Período:N"),
            y=alt.Y("Valor centavos:Q", scale=alt.Scale(domainMin=0)),
            text=alt.Text("Rótulo:N"),
        )
    )
    return alt.layer(bars, labels).properties(height=260, padding={"top": 18})


def _top_expense_rows(expenses) -> list[dict[str, str]]:
    rows = []
    for item in expenses:
        get = item.get if isinstance(item, dict) else lambda key: getattr(item, key)
        occurred_on = get("occurred_on")
        rows.append(
            {
                "Data": occurred_on.isoformat()
                if hasattr(occurred_on, "isoformat")
                else occurred_on,
                "Descrição": get("description"),
                "Pessoa": _person_label(get("person")),
                "Macro": get("category_macro"),
                "Micro": get("category_micro"),
                "Valor": format_brl(get("amount_minor_units")),
            }
        )
    return rows


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
) -> alt.Chart:
    frame = pd.DataFrame(
        [
            {
                "Período": pd.to_datetime(point.period),
                "Grupo": _person_label(point.group) if dimension == "person" else point.group,
                "Valor (centavos)": point.amount_minor_units,
            }
            for point in points
        ]
    )
    interval_selection = alt.selection_interval(encodings=["x"])
    if granularity == "month":
        time_unit = "yearmonth"
        axis_format = "%b %Y"
    elif granularity == "week":
        time_unit = "yearmonthdate"
        axis_format = "%d %b"
    else:
        time_unit = "yearmonthdate"
        axis_format = "%d %b"
    base = alt.Chart(frame).encode(
        x=alt.X(
            f"{time_unit}(Período):T",
            title=granularity.capitalize(),
            axis=alt.Axis(format=axis_format, labelAngle=-35),
        ),
        y=alt.Y(
            "sum(Valor (centavos)):Q",
            title="Gasto líquido (R$)",
            axis=alt.Axis(labelExpr="'R$ ' + format(datum.value / 100, ',.2f')"),
        ),
        tooltip=[
            alt.Tooltip(f"{time_unit}(Período):T", title="Período", format=axis_format),
            alt.Tooltip("Grupo:N", title="Detalhamento"),
            alt.Tooltip(
                "sum(Valor (centavos)):Q",
                title="Gastos (centavos)",
                format=",.0f",
            ),
        ],
    )
    if dimension == "total":
        chart = base.mark_area(point=True, line=True, opacity=0.4)
    else:
        chart = base.mark_line(point=True).encode(
            color=alt.Color("Grupo:N", title=dimension.capitalize())
        )
    return (
        chart.add_params(interval_selection)
        .interactive()
        .properties(height=380)
        .configure_view(strokeOpacity=0)
    )


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
    person = _person_map()[person_label].value
    source_kind = {
        "Conta bancária": SourceKind.BANK_ACCOUNT.value,
        "Cartão de crédito": SourceKind.CREDIT_CARD.value,
    }[source_kind_label]

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
            data={"source_key": source_key.strip(), "person": person, "source_kind": source_kind},
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
            "response": response.json(),
        }

    preview = st.session_state.get("import_preview")
    if not preview:
        return
    if (
        preview["source_key"] != source_key.strip()
        or preview["person"] != person
        or preview["source_kind"] != source_kind
    ):
        st.warning("A prévia aberta usa escolhas diferentes. Gere outra prévia antes de confirmar.")
        return
    _render_preview_and_confirmation(preview)


def _render_preview_and_confirmation(preview: dict) -> None:
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
                    {
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
        macro = st.text_input("Macro categoria", key="demo_macro")
        micro = st.text_input("Micro categoria", key="demo_micro")
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
    mapping_confirmed = st.checkbox(
        "Confirmo o mapeamento provisório: Tipo de Fluxo = macro, Fluxo = micro, "
        "Classificação = natureza; Observação contém a descrição para regra exata.",
        key="confirm_category_mapping",
    )
    workbook_path = _historical_workbook_path()
    historical_rules = None
    if mapping_confirmed and workbook_path is None:
        st.warning(
            "Mapeamento confirmado, mas a planilha não está nos locais conhecidos "
            "data/historical/ ou data/reference/. Nenhum outro local será procurado."
        )
    elif mapping_confirmed and workbook_path is not None:
        try:
            loaded = load_expense_rules(
                workbook_path.read_bytes(),
                confirm_column_mapping=True,
            )
            historical_rules = loaded.rules
            st.caption(f"Regras locais carregadas para esta sessão: {loaded.rule_count}.")
            if loaded.skipped_without_description:
                st.caption(
                    f"{loaded.skipped_without_description} linha(s) sem descrição foram ignoradas."
                )
        except HistoricalRuleError as error:
            st.error(f"Planilha não carregada ({error.code}): {error.message}")
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
                ("Despesa", "Entrada", "Transferência"),
                key=f"movement-{row['source_key']}-{row['transaction_id']}",
            )
            movement_type = {
                "Despesa": "expense",
                "Entrada": "income",
                "Transferência": "transfer",
            }[movement_label]
            suggested = (
                _get_category_suggestion(row, historical_rules)
                if movement_type == "expense" and historical_rules is not None
                else None
            )
            if suggested:
                st.info(
                    "Sugestão exata: "
                    f"{suggested['macro']} / {suggested['micro']}. Confira antes de salvar."
                )
            macro = micro = None
            if movement_type == "expense":
                macro = st.text_input(
                    "Macro categoria",
                    value=suggested["macro"] if suggested else "",
                    key=f"macro-{row['source_key']}-{row['transaction_id']}",
                )
                micro = st.text_input(
                    "Micro categoria",
                    value=suggested["micro"] if suggested else "",
                    key=f"micro-{row['source_key']}-{row['transaction_id']}",
                )
            if st.button(
                "Confirmar natureza e categoria",
                key=f"confirm-type-{row['source_key']}-{row['transaction_id']}",
            ):
                if movement_type == "expense" and (not macro or not micro):
                    st.warning("Informe macro e micro categoria para confirmar um gasto.")
                    return
                response = _api_post(
                    f"/transactions/{row['source_key']}/{row['transaction_id']}/movement-type",
                    json={
                        "movement_type": movement_type,
                        "confirmed": True,
                        "macro": macro,
                        "micro": micro,
                    },
                )
                _show_action_result(response, "Natureza salva.")


def _historical_workbook_path() -> Path | None:
    return next((path.resolve() for path in HISTORICAL_WORKBOOK_CANDIDATES if path.is_file()), None)


def _get_category_suggestion(row: dict, rules) -> dict[str, str] | None:
    if not rules:
        return None
    suggestion = _api_post(
        f"/transactions/{row['source_key']}/{row['transaction_id']}/category-suggestion",
        json={
            "rules": [
                {
                    "rule_id": rule.rule_id,
                    "description": rule.description,
                    "macro": rule.category.macro,
                    "micro": rule.category.micro,
                }
                for rule in rules
            ]
        },
    )
    if suggestion is None or suggestion.status_code != 200:
        return None
    payload = suggestion.json()
    return payload["suggested_category"] if payload["status"] == "suggested" else None


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
