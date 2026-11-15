"""End-to-end acceptance using only isolated synthetic files and databases."""

import shutil
import sqlite3
import subprocess
import sys
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from streamline_finance.api import create_app

CSV = (
    "Data,Valor,Identificador,Descrição\n"
    "03/02/2026,-12.34,synthetic-expense,COMPRA EXEMPLO\n"
    "04/02/2026,2.34,synthetic-refund,ESTORNO EXEMPLO\n"
    "05/02/2026,-50.00,synthetic-transfer,TRANSFERENCIA EXEMPLO\n"
).encode()
FORM = {"source_key": "synthetic-account", "person": "self", "source_kind": "bank_account"}
FILE = {"file": ("synthetic.csv", CSV, "text/csv")}


def test_full_acceptance_and_isolated_backup_restore(tmp_path):
    original = tmp_path / "original"
    with TestClient(create_app(data_root=original)) as client:
        preview = client.post("/imports/preview", data=FORM, files=FILE)
        assert preview.status_code == 200
        assert preview.json()["can_confirm"]
        assert all(row["movement_type"] == "pending" for row in preview.json()["transactions"])
        assert client.get("/imports").json()["imports"] == []

        saved = client.post("/imports/confirm", data={**FORM, "confirmed": "true"}, files=FILE)
        assert saved.status_code == 201
        assert saved.json()["imported_count"] == 3
        assert (
            client.get("/reports/monthly-spending", params={"month": "2026-02"}).json()[
                "total_minor_units"
            ]
            == 0
        )
        for identifier, kind, category in (
            ("synthetic-expense", "expense", {"macro": "Casa", "micro": "Mercado"}),
            ("synthetic-refund", "expense", {"macro": "Casa", "micro": "Mercado"}),
            ("synthetic-transfer", "transfer", {}),
        ):
            response = client.post(
                f"/transactions/synthetic-account/{identifier}/movement-type",
                json={"movement_type": kind, "confirmed": True, **category},
            )
            assert response.status_code == 200

        category = {"macro": "Viagens", "micro": "Transporte", "confirmed": True}
        assert client.post("/categories", json=category).status_code == 200
        report = client.get("/reports/monthly-spending", params={"month": "2026-02"}).json()
        assert report["total_minor_units"] == 1000
        assert report["transaction_count"] == 2
        suggestion = client.post(
            "/transactions/synthetic-account/synthetic-expense/category-suggestion",
            json={
                "rules": [
                    {
                        "rule_id": "synthetic-rule",
                        "description": "COMPRA EXEMPLO",
                        "macro": "Casa",
                        "micro": "Mercado",
                    }
                ]
            },
        )
        assert suggestion.json()["suggested_category"] == {"macro": "Casa", "micro": "Mercado"}

    # Back up closed db and raw sources together, then restore into a separate empty location.
    backup = tmp_path / "backup"
    backup.mkdir()
    shutil.copytree(original / "db", backup / "db")
    shutil.copytree(original / "raw", backup / "raw")
    restored = tmp_path / "restored"
    restored.mkdir()
    shutil.copytree(backup / "db", restored / "db")
    shutil.copytree(backup / "raw", restored / "raw")
    assert next((restored / "raw").iterdir()).read_bytes() == CSV
    assert next((restored / "raw").iterdir()).stem == sha256(CSV).hexdigest()
    with sqlite3.connect(restored / "db" / "finance.sqlite3") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    with TestClient(create_app(data_root=restored)) as client:
        restored_report = client.get("/reports/monthly-spending", params={"month": "2026-02"})
        assert restored_report.json() == report
        assert {
            tuple(item.values()) for item in client.get("/categories").json()["categories"]
        } >= {("Viagens", "Transporte"), ("Casa", "Mercado")}
        repeated = client.post("/imports/confirm", data={**FORM, "confirmed": "true"}, files=FILE)
        assert repeated.status_code == 200
        assert repeated.json()["already_imported"] is True
        assert len(client.get("/transactions").json()["transactions"]) == 3


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operational procedure for Windows")
def test_windows_copy_procedure_restores_synthetic_db_and_raw(tmp_path):
    data = tmp_path / "data"
    (data / "db").mkdir(parents=True)
    (data / "raw").mkdir()
    with sqlite3.connect(data / "db" / "finance.sqlite3") as connection:
        connection.execute("CREATE TABLE synthetic (value INTEGER)")
        connection.execute("INSERT INTO synthetic VALUES (42)")
    (data / "raw" / "synthetic.csv").write_bytes(CSV)
    script = """
    $ErrorActionPreference = 'Stop'
    $backup = Join-Path (Get-Location) 'backup'
    New-Item -ItemType Directory -Path $backup | Out-Null
    Copy-Item -LiteralPath 'data/db' -Destination (Join-Path $backup 'db') -Recurse
    Copy-Item -LiteralPath 'data/raw' -Destination (Join-Path $backup 'raw') -Recurse
    $ensaio = Join-Path (Get-Location) 'restore'
    New-Item -ItemType Directory -Path $ensaio | Out-Null
    Copy-Item -LiteralPath (Join-Path $backup 'db') -Destination (Join-Path $ensaio 'db') -Recurse
    Copy-Item -LiteralPath (Join-Path $backup 'raw') -Destination (Join-Path $ensaio 'raw') -Recurse
    """
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    assert (tmp_path / "restore" / "raw" / "synthetic.csv").read_bytes() == CSV
    with sqlite3.connect(tmp_path / "restore" / "db" / "finance.sqlite3") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT value FROM synthetic").fetchone() == (42,)
