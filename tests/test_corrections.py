"""Synthetic acceptance for correcting previously confirmed movements."""

from pathlib import Path

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from streamline_finance.api import create_app

CSV = (
    "Data,Valor,Identificador,Descrição\n"
    "03/09/2026,-50.00,payment-example,PAGAMENTO DE FATURA FICTICIA\n"
    "04/09/2026,-12.34,purchase-example,COMPRA FICTICIA\n"
).encode()
SOURCE = "synthetic-bank"


def test_correct_confirmed_payment_without_changing_original_or_other_expenses(tmp_path):
    root = tmp_path / "data"
    with TestClient(create_app(data_root=root)) as client:
        form = {"source_key": SOURCE, "person": "self", "confirmed": "true"}
        uploaded = {"file": ("synthetic.csv", CSV, "text/csv")}
        assert client.post("/imports/confirm", data=form, files=uploaded).status_code == 201
        for identifier in ("payment-example", "purchase-example"):
            result = client.post(
                f"/transactions/{SOURCE}/{identifier}/movement-type",
                json={
                    "movement_type": "expense",
                    "confirmed": True,
                    "macro": "Casa",
                    "micro": "Geral",
                },
            )
            assert result.status_code == 200
        path = f"/transactions/{SOURCE}/payment-example"
        before = client.get(path).json()
        assert (
            client.get("/reports/monthly-spending", params={"month": "2026-09"}).json()[
                "total_minor_units"
            ]
            == 6234
        )
        correction = {
            "expected_movement_type": "expense",
            "expected_macro": "Casa",
            "expected_micro": "Geral",
            "movement_type": "transfer",
            "confirmed": True,
        }
        assert (
            client.post(path + "/correction", json={**correction, "confirmed": False}).status_code
            == 409
        )
        assert client.post(path + "/correction", json=correction).status_code == 200
        after = client.get(path).json()
        assert after["movement_type"] == "transfer" and after["category"] is None
        for field in ("amount_minor_units", "currency", "occurred_on", "description", "source_key"):
            assert after[field] == before[field]
        assert (
            client.get("/reports/monthly-spending", params={"month": "2026-09"}).json()[
                "total_minor_units"
            ]
            == 1234
        )
        assert client.post(path + "/correction", json=correction).status_code == 409
        history = client.get(path + "/reviews").json()["reviews"]
        assert [(row["previous_value"], row["new_value"]) for row in history[-2:]] == [
            ("expense", "transfer"),
            ("category:Casa/Geral", "category:pending"),
        ]

    with TestClient(create_app(data_root=root)) as client:
        assert client.get(path).json()["movement_type"] == "transfer"
        assert (
            client.post("/imports/confirm", data=form, files=uploaded).json()["already_imported"]
            is True
        )
        assert (
            client.get("/reports/monthly-spending", params={"month": "2026-09"}).json()[
                "total_minor_units"
            ]
            == 1234
        )


def test_correct_category_and_undo_with_optimistic_state_check(tmp_path):
    with TestClient(create_app(data_root=tmp_path / "data")) as client:
        client.post(
            "/imports/confirm",
            data={"source_key": SOURCE, "person": "self", "confirmed": "true"},
            files={"file": ("synthetic.csv", CSV, "text/csv")},
        )
        path = f"/transactions/{SOURCE}/payment-example"
        assert (
            client.post(
                path + "/correction",
                json={
                    "expected_movement_type": "pending",
                    "movement_type": "expense",
                    "macro": "Casa",
                    "micro": "Geral",
                    "confirmed": True,
                },
            ).status_code
            == 409
        )
        client.post(path + "/movement-type", json={"movement_type": "transfer", "confirmed": True})
        assert (
            client.post(
                path + "/correction",
                json={
                    "expected_movement_type": "expense",
                    "movement_type": "expense",
                    "macro": "Casa",
                    "micro": "Outro",
                    "confirmed": True,
                },
            ).status_code
            == 409
        )
        assert (
            client.post(
                path + "/correction",
                json={
                    "expected_movement_type": "transfer",
                    "movement_type": "expense",
                    "macro": "Casa",
                    "micro": "Geral",
                    "confirmed": True,
                },
            ).status_code
            == 200
        )
        assert client.post(
            path + "/correction",
            json={
                "expected_movement_type": "expense",
                "expected_macro": "Casa",
                "expected_micro": "Geral",
                "movement_type": "expense",
                "macro": "Casa",
                "micro": "Outro",
                "confirmed": True,
            },
        ).json()["category"] == {"macro": "Casa", "micro": "Outro"}
        assert (
            client.post(
                path + "/correction",
                json={
                    "expected_movement_type": "expense",
                    "expected_macro": "Casa",
                    "expected_micro": "Geral",
                    "movement_type": "transfer",
                    "confirmed": True,
                },
            ).status_code
            == 409
        )
        assert (
            client.post(
                path + "/correction",
                json={
                    "expected_movement_type": "expense",
                    "expected_macro": "Casa",
                    "expected_micro": "Outro",
                    "movement_type": "transfer",
                    "micro": "Outro",
                    "confirmed": True,
                },
            ).status_code
            == 422
        )


def test_review_screen_finds_prior_payment_and_corrects_it_without_reimport(tmp_path, monkeypatch):
    import httpx2

    with TestClient(create_app(data_root=tmp_path / "local")) as client:
        assert (
            client.post(
                "/imports/confirm",
                data={"source_key": SOURCE, "person": "self", "confirmed": "true"},
                files={"file": ("synthetic.csv", CSV, "text/csv")},
            ).status_code
            == 201
        )
        for identifier in ("payment-example", "purchase-example"):
            assert (
                client.post(
                    f"/transactions/{SOURCE}/{identifier}/movement-type",
                    json={
                        "movement_type": "expense",
                        "macro": "Casa",
                        "micro": "Geral",
                        "confirmed": True,
                    },
                ).status_code
                == 200
            )
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
                json=kwargs.get("json"),
                data=kwargs.get("data"),
                files=kwargs.get("files"),
            ),
        )
        app = AppTest.from_file(
            Path(__file__).resolve().parents[1] / "app.py", default_timeout=15
        ).run()
        app.radio(key="data_mode_label").set_value("Meus dados locais").run()
        app.switch_page("pages/3_Revisar.py").run()
        app.radio(key="review_view").set_value("Já revisadas").run()
        app.selectbox(key="correction-month").select("2026-09").run()
        app.selectbox(key="correction-origin").select(SOURCE).run()
        app.text_input(key="correction-search").set_value("PAGAMENTO DE FATURA").run()
        assert not app.exception
        assert (
            app.selectbox(key="correction-transaction").value["transaction_id"] == "payment-example"
        )
        app.selectbox(key=f"correct-movement-{SOURCE}-payment-example").select(
            "Transferência"
        ).run()
        assert any("-R$ 50,00" in str(getattr(element, "value", "")) for element in app.main)
        app.checkbox(key=f"correct-ack-{SOURCE}-payment-example").check().run()
        app.button(key=f"correct-save-{SOURCE}-payment-example").click().run()
        assert not app.exception
        assert (
            client.get(f"/transactions/{SOURCE}/payment-example").json()["movement_type"]
            == "transfer"
        )
        assert (
            client.get("/reports/monthly-spending", params={"month": "2026-09"}).json()[
                "total_minor_units"
            ]
            == 1234
        )
