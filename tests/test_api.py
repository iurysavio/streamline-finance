from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from streamline_finance.api import create_app
from streamline_finance.domain import MovementType, Person
from streamline_finance.importers.nubank import preview_nubank_csv
from streamline_finance.storage import FinanceRepository

CSV_VALID = (
    b"JasData,Valor,Identificador,Descri\xc3\xa7\xc3\xa3o\n"
    b"03/02/2026,-12.34,api-synthetic-001,COMPRA FICTICIA LOJA EXEMPLO\n"
    b"04/02/2026,25.00,api-synthetic-002,TRANSFERENCIA FICTICIA\n"
)
CSV_BAD = (
    b"JasData,Valor,Identificador,Descri\xc3\xa7\xc3\xa3o\n"
    b"31/02/2026,-12.34,api-synthetic-bad,FICTICIO\n"
)


def client_for(tmp_path) -> tuple[TestClient, FinanceRepository]:
    repository = FinanceRepository(tmp_path / "data" / "db" / "finance.sqlite3")
    app = create_app(repository=repository)
    return TestClient(app), repository


def test_preview_endpoint_does_not_write_to_database_or_raw_directory(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    response = client.post(
        "/imports/preview",
        data={"source_key": "nubank-synthetic", "person": "self", "source_kind": "bank_account"},
        files={"file": ("synthetic.csv", CSV_VALID, "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["can_confirm"] is True
    assert payload["transaction_count"] == 2
    assert payload["errors"] == []
    assert payload["transactions"][0]["transaction_id"] == "api-synthetic-001"
    assert payload["transactions"][0]["amount_minor_units"] == -1234
    assert payload["transactions"][0]["movement_type"] == "pending"
    assert payload["transactions"][0]["source_fields"]["Identificador"] == "api-synthetic-001"
    assert "Data" in payload["transactions"][0]["source_fields"]
    assert "JasData" not in payload["transactions"][0]["source_fields"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert repository.list_imports() == ()
    assert repository.list_transactions() == ()
    assert list(repository.raw_directory.iterdir()) == []


def test_category_catalog_requires_confirmation_and_rejects_normalized_duplicates(tmp_path):
    client, repository = client_for(tmp_path)
    data = {"macro": "Casa", "micro": "Mercado", "confirmed": False}
    assert client.post("/categories", json=data).status_code == 409
    assert repository.list_categories() == ()
    assert client.post("/categories", json={**data, "confirmed": True}).status_code == 200
    assert (
        client.post(
            "/categories", json={"macro": " casa ", "micro": "MERCADO", "confirmed": True}
        ).status_code
        == 409
    )
    assert client.get("/categories").json()["categories"] == [{"macro": "Casa", "micro": "Mercado"}]
    assert client.get("/categories").headers["cache-control"] == "no-store"


def test_invalid_preview_returns_safe_errors_and_confirmation_is_rejected(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    preview_response = client.post(
        "/imports/preview",
        data={"source_key": "nubank-synthetic", "person": "self"},
        files={"file": ("synthetic.csv", CSV_BAD, "text/csv")},
    )

    assert preview_response.status_code == 200
    payload = preview_response.json()
    assert payload["can_confirm"] is False
    assert payload["errors"][0]["code"] == "invalid_date"
    assert "api-synthetic-bad" not in preview_response.text
    assert "FICTICIO" not in preview_response.text

    confirm_response = client.post(
        "/imports/confirm",
        data={"source_key": "nubank-synthetic", "person": "self", "confirmed": "true"},
        files={"file": ("synthetic.csv", CSV_BAD, "text/csv")},
    )
    assert confirm_response.status_code == 422
    assert repository.list_imports() == ()


def test_confirm_requires_explicit_confirmation_and_persists_only_when_true(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    form_data = {"source_key": "nubank-synthetic", "person": "self", "source_kind": "bank_account"}
    file = ("synthetic.csv", CSV_VALID, "text/csv")

    not_confirmed = client.post(
        "/imports/confirm", data={**form_data, "confirmed": "false"}, files={"file": file}
    )
    assert not_confirmed.status_code == 409
    assert repository.list_imports() == ()

    confirmed = client.post(
        "/imports/confirm", data={**form_data, "confirmed": "true"}, files={"file": file}
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["imported_count"] == 2
    assert len(repository.list_imports()) == 1
    assert len(repository.list_transactions()) == 2


def test_repeated_confirm_is_idempotent_via_api(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    form_data = {"source_key": "nubank-synthetic", "person": "self", "confirmed": "true"}
    file = ("synthetic.csv", CSV_VALID, "text/csv")

    first = client.post("/imports/confirm", data=form_data, files={"file": file})
    second = client.post("/imports/confirm", data=form_data, files={"file": file})

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["already_imported"] is True
    assert len(repository.list_transactions()) == 2


def test_transactions_endpoint_returns_normalized_rows_without_source_fields(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    repository.confirm_import(
        preview_nubank_csv(
            CSV_VALID,
            person=Person.SELF,
            source_key="nubank-synthetic",
        ),
        source_key="nubank-synthetic",
        content=CSV_VALID,
    )

    response = client.get("/transactions", params={"source_key": "nubank-synthetic"})

    assert response.status_code == 200
    rows = response.json()["transactions"]
    assert len(rows) == 2
    assert rows[0]["amount_minor_units"] == -1234
    assert rows[0]["movement_type"] == "pending"
    assert "source_fields" not in rows[0]
    assert "source_fields" not in response.text


def test_review_movement_type_requires_confirmation(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    _confirm_synthetic_file(client)

    blocked = client.post(
        "/transactions/nubank-synthetic/api-synthetic-001/movement-type",
        json={"movement_type": "expense", "confirmed": False},
    )
    accepted = client.post(
        "/transactions/nubank-synthetic/api-synthetic-001/movement-type",
        json={"movement_type": "expense", "confirmed": True},
    )

    assert blocked.status_code == 409
    assert accepted.status_code == 200
    assert accepted.json()["movement_type"] == "expense"
    assert len(repository.list_reviews("nubank-synthetic", "api-synthetic-001")) == 1


def test_category_confirmation_records_manual_choice_and_provenance(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    _confirm_synthetic_file(client)
    movement_response = client.post(
        "/transactions/nubank-synthetic/api-synthetic-001/movement-type",
        json={"movement_type": "expense", "confirmed": True},
    )
    assert movement_response.status_code == 200

    response = client.post(
        "/transactions/nubank-synthetic/api-synthetic-001/category",
        json={
            "macro": "Necessidades básicas",
            "micro": "Supermercado",
            "confirmed": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["category"]["macro"] == "Necessidades básicas"
    assert response.json()["category"]["micro"] == "Supermercado"
    row = repository.get_transaction("api-synthetic-001", source_key="nubank-synthetic")
    assert row.movement_type is MovementType.EXPENSE
    assert row.category is not None
    assert len(repository.list_reviews("nubank-synthetic", "api-synthetic-001")) == 2


def test_invalid_payloads_and_unknown_transaction_return_clear_status(tmp_path) -> None:
    client, _ = client_for(tmp_path)

    bad_person = client.post(
        "/imports/preview",
        data={"source_key": "nubank-synthetic", "person": "someone-else"},
        files={"file": ("synthetic.csv", CSV_VALID, "text/csv")},
    )
    missing_transaction = client.get("/transactions/nubank-synthetic/not-found")

    assert bad_person.status_code == 422
    assert missing_transaction.status_code == 404


def test_api_refuses_requests_from_non_loopback_client(tmp_path) -> None:
    from httpx2 import ASGITransport, AsyncClient

    app = create_app(data_root=tmp_path / "local-data")

    async def run() -> None:
        transport = ASGITransport(app=app, client=("192.0.2.12", 4567))
        async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
            response = await async_client.get("/health")
        assert response.status_code == 403

    import asyncio

    asyncio.run(run())


def test_mutating_api_routes_reject_cross_origin_browser_requests(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    response = client.post(
        "/imports/confirm",
        headers={"Origin": "http://evil.example"},
        data={
            "source_key": "nubank-synthetic",
            "person": "self",
            "source_kind": "bank_account",
            "confirmed": "true",
        },
        files={"file": ("synthetic.csv", CSV_VALID, "text/csv")},
    )

    assert response.status_code == 403
    assert repository.list_imports() == ()


def test_preview_endpoint_rejects_oversized_file_without_echoing_content(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    app = create_app(repository=repository)
    app.state.repository = repository
    oversized = b"x" * (10 * 1024 * 1024 + 1)

    response = client.post(
        "/imports/preview",
        data={"source_key": "nubank-synthetic", "person": "self"},
        files={"file": ("too-large.csv", oversized, "text/csv")},
    )

    assert response.status_code == 413
    assert "xxxxx" not in response.text
    assert repository.list_imports() == ()


def test_application_lifespan_creates_local_repository_and_health_is_available(tmp_path) -> None:
    app = create_app(data_root=tmp_path / "local-data")
    with TestClient(app) as client:
        root = client.get("/")
        response = client.get("/health")
        browser_probe = client.get("/json/version")
    assert root.status_code == 200
    assert "/docs" in root.json()["detail"]
    assert response.status_code == 200
    assert browser_probe.status_code == 404
    assert (tmp_path / "local-data" / "db" / "finance.sqlite3").exists()


def test_category_suggestion_rules_reject_unknown_fields() -> None:
    # The Pydantic payload model rejects caller-supplied extension fields.
    from streamline_finance.api import CategorySuggestionRequest

    with pytest.raises(ValidationError):
        CategorySuggestionRequest.model_validate({"rules": [], "payload": "untrusted extra data"})


def test_suggestion_endpoint_is_read_only_and_does_not_auto_confirm(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    _confirm_synthetic_file(client)
    repository.review_movement_type(
        "nubank-synthetic", "api-synthetic-001", MovementType.EXPENSE, confirm=True
    )
    request = {
        "rules": [
            {
                "rule_id": "synthetic-rule",
                "description": "COMPRA FICTICIA LOJA EXEMPLO",
                "macro": "Necessidades básicas",
                "micro": "Supermercado",
            }
        ]
    }

    first = client.post(
        "/transactions/nubank-synthetic/api-synthetic-001/category-suggestion",
        json=request,
    )
    second = client.post(
        "/transactions/nubank-synthetic/api-synthetic-001/category-suggestion",
        json=request,
    )

    assert first.status_code == 200
    assert first.json()["status"] == "suggested"
    assert first.json()["matched_rule_ids"] == ["synthetic-rule"]
    assert second.json() == first.json()
    assert (
        repository.get_transaction("api-synthetic-001", source_key="nubank-synthetic").category
        is None
    )


def test_monthly_report_includes_only_confirmed_expenses_and_returns_zero_for_empty_month(
    tmp_path,
) -> None:
    client, _ = client_for(tmp_path)
    _confirm_synthetic_file(client)
    client.post(
        "/transactions/nubank-synthetic/api-synthetic-001/movement-type",
        json={"movement_type": "expense", "confirmed": True},
    )
    client.post(
        "/transactions/nubank-synthetic/api-synthetic-001/category",
        json={"macro": "Necessidades", "micro": "Mercado", "confirmed": True},
    )

    report = client.get("/reports/monthly-spending", params={"month": "2026-02"})
    empty = client.get("/reports/monthly-spending", params={"month": "2026-03"})
    invalid_month = client.get("/reports/monthly-spending", params={"month": "2026-13"})

    assert report.status_code == 200
    assert report.json()["total_minor_units"] == 1234
    assert report.json()["formatted_brl"] == "R$ 12,34"
    assert report.json()["transaction_count"] == 1
    assert report.json()["by_category"][0]["macro"] == "Necessidades"
    assert empty.status_code == 200
    assert empty.json()["total_minor_units"] == 0
    assert empty.json()["by_category"] == []
    assert invalid_month.status_code == 422


def test_spending_trend_api_returns_grouped_rows_and_validates_range(tmp_path) -> None:
    client, repository = client_for(tmp_path)
    from streamline_finance.demo_data import make_demo_transactions

    repository.insert_demo_transactions(make_demo_transactions())

    response = client.get(
        "/reports/spending-trend",
        params={
            "start": date.today().replace(day=1).isoformat(),
            "end": date.today().isoformat(),
            "granularity": "day",
            "dimension": "person",
        },
    )
    bad_dimension = client.get(
        "/reports/spending-trend",
        params={
            "start": "2026-01-01",
            "end": "2026-02-01",
            "granularity": "day",
            "dimension": "all",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["granularity"] == "day"
    assert {point["group"] for point in payload["points"]} == {"self", "spouse", "shared"}
    assert all(point["amount_minor_units"] > 0 for point in payload["points"])
    assert bad_dimension.status_code == 422


def test_top_expenses_and_equal_length_period_comparison_api(tmp_path) -> None:
    from streamline_finance.demo_data import make_demo_transactions

    client, repository = client_for(tmp_path)
    repository.insert_demo_transactions(make_demo_transactions())
    repository.review_movement_type(
        "demo-generated", "demo-pending-01", MovementType.EXPENSE, confirm=True
    )
    start = date.today().replace(day=1)
    end = date.today()

    top = client.get(
        "/reports/top-expenses",
        params={"start": start.isoformat(), "end": end.isoformat(), "limit": 3},
    )
    comparison = client.get(
        "/reports/period-comparison",
        params={"start": start.isoformat(), "end": end.isoformat()},
    )
    uncategorized = client.get("/transactions/uncategorized")

    assert top.status_code == 200
    expenses = top.json()["expenses"]
    assert len(expenses) <= 3
    assert all(
        expenses[index]["amount_minor_units"] >= expenses[index + 1]["amount_minor_units"]
        for index in range(len(expenses) - 1)
    )
    assert comparison.status_code == 200
    compare_body = comparison.json()
    current_start = date.fromisoformat(compare_body["current_start"])
    current_end = date.fromisoformat(compare_body["current_end"])
    previous_start = date.fromisoformat(compare_body["previous_start"])
    previous_end = date.fromisoformat(compare_body["previous_end"])
    duration = (current_end - current_start).days + 1
    assert (previous_end - previous_start).days + 1 == duration
    assert (current_start - previous_end).days == 1
    assert uncategorized.status_code == 200
    assert uncategorized.json()["count"] > 0


def test_transactions_endpoint_can_filter_confirmed_expenses_without_category(tmp_path) -> None:
    from streamline_finance.demo_data import make_demo_transactions

    client, repository = client_for(tmp_path)
    repository.insert_demo_transactions(make_demo_transactions())
    repository.review_movement_type(
        "demo-generated", "demo-pending-01", MovementType.EXPENSE, confirm=True
    )

    response = client.get("/transactions", params={"uncategorized_only": "true"})

    assert response.status_code == 200
    rows = response.json()["transactions"]
    assert {row["transaction_id"] for row in rows} == {
        "demo-pending-01",
        "demo-uncategorized-01",
    }
    assert all(row["movement_type"] == "expense" and row["category"] is None for row in rows)


def test_top_expenses_endpoint_returns_individual_outflows_only_and_respects_range(tmp_path):
    from streamline_finance.demo_data import make_demo_transactions

    client, repository = client_for(tmp_path)
    repository.insert_demo_transactions(make_demo_transactions())

    response = client.get(
        "/reports/top-expenses",
        params={"start": "2026-01-01", "end": "2026-12-31", "limit": 4},
    )

    assert response.status_code == 200
    expenses = response.json()["expenses"]
    assert len(expenses) == 4
    assert all(
        expenses[i]["amount_minor_units"] >= expenses[i + 1]["amount_minor_units"] for i in range(3)
    )
    assert all("pending" not in row["transaction_id"] for row in expenses)


def test_period_comparison_reports_null_percent_for_zero_baseline(tmp_path):
    from streamline_finance.demo_data import make_demo_transactions

    client, repository = client_for(tmp_path)
    repository.insert_demo_transactions(make_demo_transactions())
    response = client.get(
        "/reports/period-comparison",
        params={"start": "1900-01-01", "end": "1900-01-07"},
    )

    assert response.status_code == 200
    assert response.json()["previous_total_minor_units"] == 0
    assert response.json()["variation_percent"] is None


def test_uncategorized_count_can_filter_by_inclusive_range_and_person(tmp_path):
    from streamline_finance.demo_data import make_demo_transactions

    client, repository = client_for(tmp_path)
    repository.insert_demo_transactions(make_demo_transactions())
    repository.review_movement_type(
        "demo-generated", "demo-pending-01", MovementType.EXPENSE, confirm=True
    )
    response = client.get(
        "/transactions/uncategorized",
        params={"start": "1900-01-01", "end": "1900-01-31", "person": "self"},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_historical_rule_preview_requires_mapping_confirmation_and_keeps_rules_ephemeral(
    tmp_path,
) -> None:
    from io import BytesIO

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Entrada"
    sheet.append(["Relatório sintético"])
    sheet.append(["Data", "Valor", "Fluxo", "Tipo de Fluxo", "Classificação", "Observação"])
    sheet.append(["2026-01-01", "10.00", "Mercado", "Necessidades", "Despesa", "Mercado Fictício"])
    content = BytesIO()
    workbook.save(content)
    client, repository = client_for(tmp_path)
    payload = content.getvalue()

    not_confirmed = client.post(
        "/categories/historical-rules/preview",
        data={"confirm_column_mapping": "false"},
        files={
            "file": (
                "synthetic.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    confirmed = client.post(
        "/categories/historical-rules/preview",
        data={"confirm_column_mapping": "true"},
        files={
            "file": (
                "synthetic.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert not_confirmed.status_code == 422
    assert confirmed.status_code == 200
    assert confirmed.json()["rule_count"] == 1
    assert confirmed.json()["rules"][0]["description"] == "Mercado Fictício"
    assert repository.list_imports() == ()
    assert repository.list_transactions() == ()


def _confirm_synthetic_file(client: TestClient) -> None:
    response = client.post(
        "/imports/confirm",
        data={
            "source_key": "nubank-synthetic",
            "person": "self",
            "source_kind": "bank_account",
            "confirmed": "true",
        },
        files={"file": ("synthetic.csv", CSV_VALID, "text/csv")},
    )
    assert response.status_code == 201
