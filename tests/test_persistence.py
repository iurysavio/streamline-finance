import os
import stat
from hashlib import sha256

import pytest

from streamline_finance.domain import Category, MovementType, Person, SourceKind
from streamline_finance.importers.nubank import preview_nubank_csv
from streamline_finance.storage import (
    FinanceRepository,
    ImportConflictError,
    ImportRejectedError,
    MatchDecision,
    MatchStatus,
)

CSV_ONE = (
    b"JasData,Valor,Identificador,Descri\xc3\xa7\xc3\xa3o\n"
    b"03/02/2026,-12.34,synthetic-row-001,COMPRA FICTICIA LOJA EXEMPLO\n"
    b"04/02/2026,25.00,synthetic-row-002,TRANSFERENCIA FICTICIA\n"
)
CSV_OVERLAP = (
    b"JasData,Valor,Identificador,Descri\xc3\xa7\xc3\xa3o\n"
    b"03/02/2026,-12.34,synthetic-row-001,COMPRA FICTICIA LOJA EXEMPLO\n"
    b"05/02/2026,-8.00,synthetic-row-003,OUTRA COMPRA FICTICIA\n"
)


def preview(
    content: bytes,
    person: Person = Person.SELF,
    source_key: str = "nubank-main",
    source_kind: SourceKind = SourceKind.BANK_ACCOUNT,
):
    return preview_nubank_csv(
        content, person=person, source_key=source_key, source_kind=source_kind
    )


def test_confirm_import_persists_exact_values_and_import_metadata(tmp_path) -> None:
    database = tmp_path / "data" / "db" / "finance.sqlite3"

    with FinanceRepository(database) as repository:
        result = repository.confirm_import(
            preview(CSV_ONE, source_key="nubank-main"),
            source_key="nubank-main",
            content=CSV_ONE,
        )
        transactions = repository.list_transactions()
        batches = repository.list_imports()

    assert result.imported_count == 2
    assert result.duplicate_count == 0
    assert result.already_imported is False
    assert len(batches) == 1
    assert batches[0].source_key == "nubank-main"
    assert batches[0].content_sha256 == sha256(CSV_ONE).hexdigest()
    assert batches[0].raw_filename == f"{sha256(CSV_ONE).hexdigest()}.csv"
    assert batches[0].person is Person.SELF
    assert batches[0].source_kind is SourceKind.BANK_ACCOUNT
    if os.name == "posix":
        assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert len(transactions) == 2
    assert transactions[0].amount_minor_units == -1234
    assert transactions[0].currency == "BRL"
    assert transactions[0].movement_type is MovementType.PENDING
    assert transactions[0].person is Person.SELF
    assert not database.read_bytes().startswith(CSV_ONE)
    assert (tmp_path / "data" / "raw" / batches[0].raw_filename).read_bytes() == CSV_ONE
    if os.name == "posix":
        assert (
            stat.S_IMODE((tmp_path / "data" / "raw" / batches[0].raw_filename).stat().st_mode)
            == 0o600
        )


def test_category_catalog_migrates_existing_database_and_persists_without_changing_transactions(
    tmp_path,
):
    database = tmp_path / "data" / "db" / "finance.sqlite3"
    with FinanceRepository(database) as repository:
        repository.confirm_import(
            preview(CSV_ONE, source_key="test"), source_key="test", content=CSV_ONE
        )
        before = repository.list_transactions()
        repository._connection.execute("DROP TABLE categories")
        repository._connection.commit()
    with FinanceRepository(database) as repository:
        assert repository.list_transactions() == before
        repository.add_category(Category("Casa", "Mercado"))
        with pytest.raises(ValueError):
            repository.add_category(Category(" casa ", " MERCADO "))
        with pytest.raises(ValueError):
            repository.add_category(Category("CASA", "Outro"))
    with FinanceRepository(database) as repository:
        assert repository.list_categories() == (Category("Casa", "Mercado"),)
        assert repository.list_transactions() == before


def test_reimporting_same_file_is_idempotent(tmp_path) -> None:
    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        first = repository.confirm_import(
            preview(CSV_ONE, source_key="nubank-main"),
            source_key="nubank-main",
            content=CSV_ONE,
        )
        second = repository.confirm_import(
            preview(CSV_ONE, source_key="nubank-main"),
            source_key="nubank-main",
            content=CSV_ONE,
        )

        assert first.imported_count == 2
        assert second.already_imported is True
        assert second.imported_count == 0
        assert second.duplicate_count == 2
        assert second.batch_id == first.batch_id
        assert len(repository.list_transactions()) == 2
        assert len(repository.list_imports()) == 1


def test_new_file_with_same_transaction_id_skips_existing_and_adds_new_rows(tmp_path) -> None:
    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        repository.confirm_import(
            preview(CSV_ONE, source_key="nubank-main"),
            source_key="nubank-main",
            content=CSV_ONE,
        )

        result = repository.confirm_import(
            preview(CSV_OVERLAP, source_key="nubank-main"),
            source_key="nubank-main",
            content=CSV_OVERLAP,
        )

        assert result.imported_count == 1
        assert result.duplicate_count == 1
        assert result.already_imported is False
        assert len(repository.list_transactions()) == 3
        assert len(repository.list_imports()) == 2


def test_same_identifier_with_changed_content_aborts_entire_batch(tmp_path) -> None:
    original = CSV_ONE
    changed = (
        b"JasData,Valor,Identificador,Descri\xc3\xa7\xc3\xa3o\n"
        b"03/02/2026,-99.99,synthetic-row-001,LINHA FICTICIA ALTERADA\n"
        b"05/02/2026,-8.00,synthetic-row-003,OUTRA COMPRA FICTICIA\n"
    )

    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        repository.confirm_import(
            preview(original, source_key="nubank-main"),
            source_key="nubank-main",
            content=original,
        )

        with pytest.raises(ImportConflictError):
            repository.confirm_import(
                preview(changed, source_key="nubank-main"),
                source_key="nubank-main",
                content=changed,
            )

        assert len(repository.list_transactions()) == 2
        assert len(repository.list_imports()) == 1


def test_same_identifier_in_another_source_account_is_not_duplicate(tmp_path) -> None:
    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        repository.confirm_import(
            preview(CSV_ONE, source_key="nubank-main"),
            source_key="nubank-main",
            content=CSV_ONE,
        )

        result = repository.confirm_import(
            preview(CSV_ONE, Person.SPOUSE, "nubank-spouse"),
            source_key="nubank-spouse",
            content=CSV_ONE,
        )

        assert result.imported_count == 2
        assert result.duplicate_count == 0
        assert len(repository.list_transactions()) == 4


def test_same_file_for_different_person_is_a_conflict_not_a_silent_skip(tmp_path) -> None:
    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        repository.confirm_import(
            preview(CSV_ONE, source_key="nubank-main"),
            source_key="nubank-main",
            content=CSV_ONE,
        )

        with pytest.raises(ImportConflictError):
            repository.confirm_import(
                preview(CSV_ONE, Person.SPOUSE, "nubank-main"),
                source_key="nubank-main",
                content=CSV_ONE,
            )

        assert len(repository.list_imports()) == 1
        assert len(repository.list_transactions()) == 2


def test_invalid_preview_cannot_be_confirmed_or_create_import_records(tmp_path) -> None:
    invalid = preview_nubank_csv(
        "JasData,Valor,Identificador,Descrição\n31/02/2026,-1.00,synthetic-001,FICTICIO\n",
        person=Person.SELF,
    )

    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        with pytest.raises(ImportRejectedError):
            repository.confirm_import(invalid, source_key="nubank-main", content=b"invalid")

        assert repository.list_imports() == ()
        assert repository.list_transactions() == ()


def test_database_is_created_in_local_data_db_directory(tmp_path) -> None:
    project_data = tmp_path / "data"
    database = project_data / "db" / "finance.sqlite3"

    with FinanceRepository(database) as repository:
        assert repository.list_transactions() == ()

    assert database.exists()
    assert database.parent == project_data / "db"
    assert (project_data / "raw").is_dir()
    if os.name == "posix":
        assert stat.S_IMODE(database.stat().st_mode) == 0o600
        assert stat.S_IMODE((project_data / "db").stat().st_mode) == 0o700
        assert stat.S_IMODE((project_data / "raw").stat().st_mode) == 0o700


def test_identical_amounts_with_different_transaction_ids_are_preserved(tmp_path) -> None:
    csv_text = (
        "JasData,Valor,Identificador,Descrição\n"
        "03/02/2026,-10.00,synthetic-row-001,COMPRA FICTICIA A\n"
        "03/02/2026,-10.00,synthetic-row-002,COMPRA FICTICIA B\n"
    ).encode()

    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        result = repository.confirm_import(
            preview(csv_text), source_key="nubank-main", content=csv_text
        )

        assert result.imported_count == 2
        assert len(repository.list_transactions()) == 2


def test_candidate_payment_link_requires_exact_amount_window_and_review(tmp_path) -> None:
    charge_csv = make_csv("synthetic-card-charge", "-50.00", "COMPRA FICTICIA", "03/02/2026")
    payment_csv = make_csv(
        "synthetic-bank-payment", "-50.00", "Pagamento de fatura cartao de credito", "05/02/2026"
    )

    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        repository.confirm_import(
            preview(
                charge_csv,
                source_key="card-main",
                source_kind=SourceKind.CREDIT_CARD,
            ),
            source_key="card-main",
            content=charge_csv,
        )
        repository.confirm_import(
            preview(payment_csv), source_key="nubank-main", content=payment_csv
        )
        repository.review_movement_type(
            "card-main", "synthetic-card-charge", MovementType.EXPENSE, confirm=True
        )
        repository.review_movement_type(
            "nubank-main", "synthetic-bank-payment", MovementType.TRANSFER, confirm=True
        )

        matches = repository.refresh_payment_candidates(window_days=5)

        assert len(matches) == 1
        match = matches[0]
        assert match.status is MatchStatus.PENDING
        assert match.amount_minor_units == 5000
        assert match.expense_transaction_id == "synthetic-card-charge"
        assert match.payment_transaction_id == "synthetic-bank-payment"
        assert (
            repository.get_transaction(
                "synthetic-card-charge", source_key="card-main"
            ).movement_type
            is MovementType.EXPENSE
        )
        assert (
            repository.get_transaction(
                "synthetic-bank-payment", source_key="nubank-main"
            ).movement_type
            is MovementType.TRANSFER
        )


def test_payment_candidate_is_not_created_for_near_amount_or_out_of_window(tmp_path) -> None:
    charge_csv = make_csv("synthetic-charge", "-50.00", "COMPRA FICTICIA", "01/01/2026")
    payment_csv = make_csv(
        "synthetic-payment", "-50.01", "Pagamento de fatura cartao", "01/02/2026"
    )

    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        repository.confirm_import(
            preview(
                charge_csv,
                source_key="card-main",
                source_kind=SourceKind.CREDIT_CARD,
            ),
            source_key="card-main",
            content=charge_csv,
        )
        repository.confirm_import(
            preview(payment_csv), source_key="nubank-main", content=payment_csv
        )
        repository.review_movement_type(
            "card-main", "synthetic-charge", MovementType.EXPENSE, confirm=True
        )
        repository.review_movement_type(
            "nubank-main", "synthetic-payment", MovementType.TRANSFER, confirm=True
        )

        assert repository.refresh_payment_candidates(window_days=5) == ()


def test_payment_candidate_decision_is_reversible_without_modifying_movements(tmp_path) -> None:
    charge_csv = make_csv("synthetic-charge", "-50.00", "COMPRA FICTICIA", "03/02/2026")
    payment_csv = make_csv(
        "synthetic-payment", "-50.00", "Pagamento de fatura cartao", "05/02/2026"
    )

    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        repository.confirm_import(
            preview(
                charge_csv,
                source_key="card-main",
                source_kind=SourceKind.CREDIT_CARD,
            ),
            source_key="card-main",
            content=charge_csv,
        )
        repository.confirm_import(
            preview(payment_csv), source_key="nubank-main", content=payment_csv
        )
        repository.review_movement_type(
            "card-main", "synthetic-charge", MovementType.EXPENSE, confirm=True
        )
        repository.review_movement_type(
            "nubank-main", "synthetic-payment", MovementType.TRANSFER, confirm=True
        )
        candidate = repository.refresh_payment_candidates(window_days=5)[0]

        rejected = repository.decide_payment_candidate(candidate.candidate_id, MatchDecision.REJECT)
        accepted = repository.decide_payment_candidate(candidate.candidate_id, MatchDecision.ACCEPT)
        reset = repository.decide_payment_candidate(candidate.candidate_id, MatchDecision.RESET)

        assert rejected.status is MatchStatus.REJECTED
        assert accepted.status is MatchStatus.ACCEPTED
        assert reset.status is MatchStatus.PENDING
        assert (
            repository.get_transaction("synthetic-charge", source_key="card-main").movement_type
            is MovementType.EXPENSE
        )
        assert (
            repository.get_transaction("synthetic-payment", source_key="nubank-main").movement_type
            is MovementType.TRANSFER
        )


def test_movement_type_changes_require_explicit_review_and_cannot_be_silently_rewritten(
    tmp_path,
) -> None:
    csv_content = make_csv(
        "synthetic-incoming", "100.00", "Transferencia Ficticia Recebida", "05/02/2026"
    )

    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        repository.confirm_import(
            preview(csv_content), source_key="nubank-main", content=csv_content
        )

        with pytest.raises(ValueError):
            repository.review_movement_type(
                "nubank-main", "synthetic-incoming", MovementType.INCOME
            )

        reviewed = repository.review_movement_type(
            "nubank-main",
            "synthetic-incoming",
            MovementType.INCOME,
            confirm=True,
        )
        assert reviewed.movement_type is MovementType.INCOME


def test_reimport_after_movement_review_preserves_review_and_records_provenance(tmp_path) -> None:
    content = make_csv("synthetic-row", "100.00", "RECEBIMENTO FICTICIO", "05/02/2026")

    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        repository.confirm_import(
            preview(content, source_key="nubank-main"),
            source_key="nubank-main",
            content=content,
        )
        repository.review_movement_type(
            "nubank-main", "synthetic-row", MovementType.INCOME, confirm=True
        )
        result = repository.confirm_import(
            preview(content, source_key="nubank-main"),
            source_key="nubank-main",
            content=content,
        )

        assert result.already_imported
        assert (
            repository.get_transaction("synthetic-row", source_key="nubank-main").movement_type
            is MovementType.INCOME
        )
        assert len(repository.list_reviews("nubank-main", "synthetic-row")) == 1


def test_purchase_transfer_is_not_considered_a_credit_card_payment_candidate(tmp_path) -> None:
    charge_csv = make_csv("synthetic-charge", "-50.00", "COMPRA FICTICIA", "03/02/2026")
    transfer_csv = make_csv(
        "synthetic-transfer", "-50.00", "Transferencia para amigo", "05/02/2026"
    )

    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        repository.confirm_import(
            preview(charge_csv, source_key="card-main", source_kind=SourceKind.CREDIT_CARD),
            source_key="card-main",
            content=charge_csv,
        )
        repository.confirm_import(
            preview(transfer_csv), source_key="nubank-main", content=transfer_csv
        )
        repository.review_movement_type(
            "card-main", "synthetic-charge", MovementType.EXPENSE, confirm=True
        )
        repository.review_movement_type(
            "nubank-main", "synthetic-transfer", MovementType.TRANSFER, confirm=True
        )

        assert repository.refresh_payment_candidates(window_days=5) == ()


def test_source_key_is_required_and_validated(tmp_path) -> None:
    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        with pytest.raises(ValueError):
            repository.confirm_import(preview(CSV_ONE), source_key=" ", content=CSV_ONE)


def test_confirmed_source_must_match_preview_source(tmp_path) -> None:
    with FinanceRepository(tmp_path / "finance.sqlite3") as repository:
        with pytest.raises(ImportRejectedError):
            repository.confirm_import(
                preview(CSV_ONE, source_key="account-A"),
                source_key="account-B",
                content=CSV_ONE,
            )


def make_csv(transaction_id: str, amount: str, description: str, occurred_on: str) -> bytes:
    return (
        "JasData,Valor,Identificador,Descrição\n"
        f'{occurred_on},{amount},{transaction_id},"{description}"\n'
    ).encode()
