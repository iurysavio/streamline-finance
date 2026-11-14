import csv
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_statement_fixture_matches_known_headers_and_formats() -> None:
    fixture = ROOT / "tests" / "fixtures" / "nubank_statement_synthetic.csv"

    with fixture.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = list(reader)

    assert reader.fieldnames == ["JasData", "Valor", "Identificador", "Descrição"]
    assert len(rows) == 2
    assert datetime.strptime(rows[0]["JasData"], "%d/%m/%Y").date().isoformat() == "2026-02-03"
    assert Decimal(rows[0]["Valor"]) == Decimal("-12.34")
    assert rows[0]["Identificador"].startswith("synthetic-")
    assert "FICTICIA" in rows[0]["Descrição"]


def test_repository_gitignore_excludes_financial_data_and_local_database() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "/data/" in gitignore
    assert "*.db" in gitignore
    assert "*.sqlite" in gitignore
    assert "*.sqlite3" in gitignore

    probe = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", "data/__privacy_probe__.csv"],
        cwd=ROOT,
        check=False,
    )

    assert probe.returncode == 0


def test_project_is_packaged_for_uv_run_imports() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[build-system]" in pyproject
    assert "[tool.setuptools.packages.find]" in pyproject
    assert 'where = ["src"]' in pyproject
