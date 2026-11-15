"""Multipage Streamlit entrypoint; routes pages and shared Demo/Real mode."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Finanças da Família Sávio", page_icon="💰", layout="wide")


def _navigation():
    pages = [
        st.Page(
            "pages/1_Análise.py",
            title="Análise de gastos",
            icon=":material/monitoring:",
            url_path="analise",
            default=True,
            help=(
                "Tendência de gastos líquidos por período e detalhamento por pessoa ou categoria."
            ),
        ),
        st.Page(
            "pages/2_Importar.py",
            title="Importar extrato",
            icon=":material/upload_file:",
            url_path="importar",
            help="Gere prévia, confira o CSV e confirme explicitamente antes de salvar.",
        ),
        st.Page(
            "pages/3_Revisar.py",
            title="Revisar movimentações",
            icon=":material/rule:",
            url_path="revisar",
            help=("Confirme natureza e categoria pendentes. Sugestões nunca se aplicam sozinhas."),
        ),
    ]
    st.sidebar.divider()
    return st.navigation(pages, position="sidebar", expanded=True)


with st.sidebar:
    st.title("Finanças da Família Sávio")
    mode_label = st.radio(
        "Dados para explorar",
        ("Demo — fictício", "Meus dados locais"),
        key="data_mode_label",
        horizontal=False,
    )
    previous_mode = st.session_state.get("data_mode")
    next_mode = "demo" if mode_label.startswith("Demo") else "real"
    if previous_mode == "demo" and next_mode == "real":
        st.session_state.pop("demo_transactions", None)
        st.session_state.pop("demo_upload_preview", None)
        st.session_state.pop("demo_categories", None)
    st.session_state["data_mode"] = "demo" if mode_label.startswith("Demo") else "real"
    if st.session_state["data_mode"] == "demo":
        st.caption("Sandbox temporário: alterações de demonstração não são salvas no banco.")

page = _navigation()
page.run()
