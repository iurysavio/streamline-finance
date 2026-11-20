from pathlib import Path

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from streamline_finance.api import create_app
from streamline_finance.domain import Person
from streamline_finance.importers.nubank import preview_nubank_csv
from streamline_finance.storage import FinanceRepository


def test_invoice_import_is_idempotent_and_blocks_changed_same_month(tmp_path):
    content = ('date,title,amount\n2026-09-03,Compra Fictícia,"12,34"\n').encode()
    data = {
        "source_key": "synthetic-card",
        "person": "self",
        "source_kind": "credit_card",
        "import_format": "nubank_invoice",
        "invoice_month": "2026-09",
    }
    file = {"file": ("synthetic.csv", content, "text/csv")}
    with TestClient(create_app(data_root=tmp_path / "data")) as client:
        assert client.post("/imports/preview", data=data, files=file).json()["can_confirm"]
        assert client.get("/imports").json()["imports"] == []
        first = client.post("/imports/confirm", data={**data, "confirmed": "true"}, files=file)
        assert first.status_code == 201
        repeated = client.post("/imports/confirm", data={**data, "confirmed": "true"}, files=file)
        assert repeated.status_code == 200 and repeated.json()["already_imported"]
        changed = {"file": ("synthetic.csv", content + b'2026-09-04,Outro,"1,00"\n', "text/csv")}
        assert (
            client.post(
                "/imports/confirm", data={**data, "confirmed": "true"}, files=changed
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/imports/confirm",
                data={**data, "invoice_month": "2026-10", "confirmed": "true"},
                files=file,
            ).status_code
            == 422
        )
        assert len(client.get("/transactions").json()["transactions"]) == 1


def test_overlapping_invoice_rows_blocked_across_months_without_dropping_legitimate_rows(tmp_path):
    row = '2026-09-03,Compra Fictícia,"12,34"\n'
    content = ("date,title,amount\n" + row + row).encode()
    data = {
        "source_key": "synthetic-card",
        "person": "self",
        "source_kind": "credit_card",
        "import_format": "nubank_invoice",
        "invoice_month": "2026-09",
        "confirmed": "true",
    }
    with TestClient(create_app(data_root=tmp_path / "data")) as client:
        assert (
            client.post(
                "/imports/confirm", data=data, files={"file": ("a.csv", content, "text/csv")}
            ).json()["imported_count"]
            == 2
        )
        overlap = ("date,title,amount\n" + row).encode()
        result = client.post(
            "/imports/confirm",
            data={**data, "invoice_month": "2026-10"},
            files={"file": ("b.csv", overlap, "text/csv")},
        )
        assert result.status_code == 422
        assert len(client.get("/transactions").json()["transactions"]) == 2


def test_c6_card_preview_and_confirmation_require_month_and_preserve_existing_bank_data(tmp_path):
    bank = b"Data,Valor,Identificador,Descri\xc3\xa7\xc3\xa3o\n01/09/2026,-2.00,bank-1,Teste\n"
    c6 = (
        "Data de Compra;Nome no Cartão;Final do Cartão;Categoria;Descrição;Parcela;"
        "Valor (em US$);Cotação (em R$);Valor (em R$)\n"
        "03/07/2026;Fictício;0000;Casa;Loja;Única;0.00;0.00;12.34\n"
    ).encode()
    data = {
        "source_key": "synthetic-card",
        "person": "self",
        "source_kind": "credit_card",
        "import_format": "c6_invoice",
    }
    with TestClient(create_app(data_root=tmp_path / "data")) as client:
        assert (
            client.post(
                "/imports/confirm",
                data={"source_key": "bank", "person": "self", "confirmed": "true"},
                files={"file": ("bank.csv", bank, "text/csv")},
            ).status_code
            == 201
        )
        file = {"file": ("invoice.csv", c6, "text/csv")}
        assert client.post("/imports/preview", data=data, files=file).status_code == 422
        assert (
            client.post(
                "/imports/preview",
                data={**data, "invoice_month": "2026-09", "source_kind": "bank_account"},
                files=file,
            ).status_code
            == 422
        )
        response = client.post(
            "/imports/confirm",
            data={**data, "invoice_month": "2026-09", "confirmed": "true"},
            files=file,
        )
        assert response.status_code == 201
        transactions = client.get("/transactions").json()["transactions"]
        assert len(transactions) == 2
        assert {row["amount_minor_units"] for row in transactions} == {-200, -1234}
        assert all(row["movement_type"] == "pending" for row in transactions)
        invoice_row = next(row for row in transactions if row["invoice_month"])
        assert invoice_row["invoice_month"] == "2026-09"
        assert invoice_row["occurred_on"] == "2026-07-03"
        assert (
            client.get("/reports/monthly-spending", params={"month": "2026-09"}).json()[
                "transaction_count"
            ]
            == 0
        )
        transaction_id = next(row["transaction_id"] for row in transactions if row["invoice_month"])
        assert (
            client.post(
                f"/transactions/synthetic-card/{transaction_id}/movement-type",
                json={"movement_type": "expense", "confirmed": True},
            ).status_code
            == 200
        )
        assert (
            client.get("/reports/monthly-spending", params={"month": "2026-09"}).json()[
                "total_minor_units"
            ]
            == 1234
        )
        assert (
            client.get("/reports/monthly-spending", params={"month": "2026-07"}).json()[
                "total_minor_units"
            ]
            == 0
        )


def test_additive_invoice_migration_preserves_existing_database(tmp_path):
    database = tmp_path / "data" / "db" / "finance.sqlite3"
    with FinanceRepository(database) as repository:
        content = (
            b"Data,Valor,Identificador,Descri\xc3\xa7\xc3\xa3o\n01/09/2026,-2.00,bank-1,Teste\n"
        )
        repository.confirm_import(
            preview_nubank_csv(content, person=Person.SELF, source_key="bank"),
            source_key="bank",
            content=content,
        )
        before = repository.list_transactions()
        repository._connection.execute("DROP TABLE card_invoices")
        repository._connection.commit()
    with FinanceRepository(database) as repository:
        assert repository.list_transactions() == before
        assert (
            repository._connection.execute("SELECT COUNT(*) FROM card_invoices").fetchone()[0] == 0
        )


def test_c6_ui_preview_and_confirm_with_isolated_database(tmp_path, monkeypatch):
    import httpx2

    content = (
        "Data de Compra;Nome no Cartão;Final do Cartão;Categoria;Descrição;Parcela;"
        "Valor (em US$);Cotação (em R$);Valor (em R$)\n"
        "03/09/2026;Fictício;0000;Casa;Loja;Única;0.00;0.00;12.34\n"
    ).encode()
    with TestClient(create_app(data_root=tmp_path / "data")) as client:
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
                url.removeprefix("http://127.0.0.1:8000"),
                data=kwargs.get("data"),
                files=kwargs.get("files"),
                json=kwargs.get("json"),
            ),
        )
        app = AppTest.from_file(
            Path(__file__).resolve().parents[1] / "app.py", default_timeout=15
        ).run()
        app.radio(key="data_mode_label").set_value("Meus dados locais").run()
        app.switch_page("pages/2_Importar.py").run()
        next(item for item in app.selectbox if item.label == "Formato do arquivo").select(
            "Fatura C6"
        ).run()
        next(item for item in app.selectbox if item.label == "Tipo da origem").select(
            "Cartão de crédito"
        ).run()
        app.text_input[0].set_value("synthetic-card").run()
        app.checkbox(key="source_mapping_ack").check().run()
        app.file_uploader[0].upload("synthetic.csv", content, "text/csv").run()
        next(item for item in app.button if item.label == "Gerar prévia").click().run()
        assert not app.exception
        assert any(item.value == "Prévia antes de salvar" for item in app.subheader)
        assert client.get("/imports").json()["imports"] == []
        app.checkbox(key="confirm_import_ack").check().run()
        app.button(key="confirm-import").click().run()
        assert not app.exception
        assert len(client.get("/imports").json()["imports"]) == 1
