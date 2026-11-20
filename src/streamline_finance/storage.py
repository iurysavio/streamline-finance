"""Local SQLite repository for confirmed imports and reviewable payment candidates."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from functools import wraps
from hashlib import sha256
from pathlib import Path

from streamline_finance.domain import Category, MovementType, Person, SourceKind, Transaction
from streamline_finance.importers.nubank import ImportPreview, PreviewTransaction


class ImportRejectedError(ValueError):
    """Raised when an invalid preview is sent for confirmation."""


class ImportConflictError(ValueError):
    """Raised when a source identifier is reused for different transaction data."""


class MatchStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class MatchDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    RESET = "reset"


@dataclass(frozen=True, slots=True)
class ImportResult:
    batch_id: int
    imported_count: int
    duplicate_count: int
    already_imported: bool


@dataclass(frozen=True, slots=True)
class ImportRecord:
    batch_id: int
    source_key: str
    content_sha256: str
    imported_at: str
    row_count: int
    raw_filename: str
    person: Person
    source_kind: SourceKind


@dataclass(frozen=True, slots=True)
class StoredTransaction:
    transaction_id: str
    source_key: str
    description: str
    amount_minor_units: int
    currency: str
    movement_type: MovementType
    person: Person
    occurred_on: date
    posted_on: date | None
    category: Category | None
    source_kind: SourceKind
    invoice_month: str | None = None


@dataclass(frozen=True, slots=True)
class PaymentCandidate:
    candidate_id: int
    expense_transaction_id: str
    payment_transaction_id: str
    amount_minor_units: int
    day_difference: int
    status: MatchStatus


def _serialized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class FinanceRepository:
    """SQLite access. Every write is local, parameterized, and transaction-scoped."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        local_data_root = (
            self.database_path.parent.parent
            if self.database_path.parent.name == "db"
            else self.database_path.parent
        )
        self.raw_directory = local_data_root / "raw"
        self.raw_directory.mkdir(parents=True, exist_ok=True)
        self._secure_directory(local_data_root)
        self._secure_directory(self.database_path.parent)
        self._secure_directory(self.raw_directory)
        self._lock = threading.RLock()
        if not self.database_path.exists():
            descriptor = os.open(self.database_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(descriptor)
        else:
            os.chmod(self.database_path, 0o600)
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = DELETE")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute("PRAGMA secure_delete = ON")
        self._initialize_schema()

    @staticmethod
    def _secure_directory(path: Path) -> None:
        try:
            os.chmod(path, 0o700)
        except OSError as error:
            raise OSError(
                f"Cannot restrict permissions for local finance directory: {path}"
            ) from error

    def __enter__(self) -> FinanceRepository:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @_serialized
    def close(self) -> None:
        self._connection.close()

    @_serialized
    def confirm_import(
        self,
        preview: ImportPreview,
        *,
        source_key: str,
        content: str | bytes,
    ) -> ImportResult:
        """Persist a user-confirmed valid preview atomically, without raw file contents."""
        normalized_source = source_key.strip()
        if not normalized_source:
            raise ValueError("source_key is required")
        if not preview.can_confirm:
            raise ImportRejectedError("Import preview is invalid or has not been reviewed")
        if any(row.transaction.source_key != normalized_source for row in preview.transactions):
            raise ImportRejectedError(
                "Preview source key must match the explicitly confirmed source key"
            )

        raw_bytes = content.encode("utf-8") if isinstance(content, str) else content
        digest = sha256(raw_bytes).hexdigest()
        person = _preview_person(preview)
        source_kind = _preview_source_kind(preview)
        file_fingerprint = _file_fingerprint(
            preview, source_key=normalized_source, content_sha256=digest
        )
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_batch = connection.execute(
                "SELECT id, row_count, raw_filename, person, source_kind, file_fingerprint "
                "FROM import_batches "
                "WHERE source_key = ? AND content_sha256 = ?",
                (normalized_source, digest),
            ).fetchone()
            if preview.invoice_format is not None:
                if preview.invoice_month is None or source_kind is not SourceKind.CREDIT_CARD:
                    raise ImportRejectedError("Fatura exige cartão e competência")
                existing_invoice = connection.execute(
                    "SELECT batch_id FROM card_invoices WHERE source_key = ? AND invoice_month = ?",
                    (normalized_source, preview.invoice_month),
                ).fetchone()
                if existing_invoice is not None and (
                    existing_batch is None or existing_invoice["batch_id"] != existing_batch["id"]
                ):
                    raise ImportConflictError(
                        "Já existe fatura para este cartão e competência; "
                        "revise antes de substituir."
                    )
                if existing_batch is not None and (
                    existing_invoice is None or existing_invoice["batch_id"] != existing_batch["id"]
                ):
                    raise ImportConflictError(
                        "Arquivo já importado com outra competência ou formato."
                    )
                other_format = connection.execute(
                    "SELECT 1 FROM card_invoices WHERE source_key = ? "
                    "AND invoice_format != ? LIMIT 1",
                    (normalized_source, preview.invoice_format),
                ).fetchone()
                if other_format is not None:
                    raise ImportConflictError(
                        "A identificação do cartão já foi usada com outro formato."
                    )
                if existing_batch is None:
                    for row in preview.transactions:
                        fields = json.dumps(
                            dict(row.source_fields), ensure_ascii=False, separators=(",", ":")
                        )
                        overlap = connection.execute(
                            "SELECT 1 FROM transactions t JOIN import_batch_transactions links "
                            "ON links.transaction_id = t.id JOIN card_invoices i "
                            "ON i.batch_id = links.batch_id "
                            "WHERE i.source_key = ? AND t.source_fields_json = ? LIMIT 1",
                            (normalized_source, fields),
                        ).fetchone()
                        if overlap:
                            raise ImportConflictError(
                                "Lançamento semelhante já existe em outra fatura; "
                                "revisão manual necessária."
                            )
            if existing_batch is not None:
                if (
                    existing_batch["person"] != person.value
                    or existing_batch["source_kind"] != source_kind.value
                    or existing_batch["file_fingerprint"] != file_fingerprint
                ):
                    raise ImportConflictError(
                        "The same file/source was previously imported with different "
                        "review choices."
                    )
                existing_raw_path = self.raw_directory / existing_batch["raw_filename"]
                if (
                    not existing_raw_path.is_file()
                    or sha256(existing_raw_path.read_bytes()).hexdigest() != digest
                ):
                    raise ImportConflictError(
                        "Stored raw source is missing or its integrity check failed."
                    )
                connection.rollback()
                return ImportResult(
                    batch_id=existing_batch["id"],
                    imported_count=0,
                    duplicate_count=existing_batch["row_count"],
                    already_imported=True,
                )

            raw_filename = f"{digest}.csv"
            raw_path = self.raw_directory / raw_filename
            if raw_path.exists() and sha256(raw_path.read_bytes()).hexdigest() != digest:
                raise ImportConflictError("A raw import object hash did not match its contents")
            if not raw_path.exists():
                descriptor = os.open(raw_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as raw_file:
                    raw_file.write(raw_bytes)

            cursor = connection.execute(
                """INSERT INTO import_batches (
                       source_key, content_sha256, imported_at, row_count, raw_filename,
                       person, source_kind, file_fingerprint
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    normalized_source,
                    digest,
                    _now(),
                    len(preview.transactions),
                    raw_filename,
                    person.value,
                    source_kind.value,
                    file_fingerprint,
                ),
            )
            batch_id = int(cursor.lastrowid)
            if preview.invoice_format is not None:
                connection.execute(
                    "INSERT INTO card_invoices (batch_id, source_key, invoice_month, "
                    "invoice_format) "
                    "VALUES (?, ?, ?, ?)",
                    (batch_id, normalized_source, preview.invoice_month, preview.invoice_format),
                )
            imported_count = 0
            duplicate_count = 0
            for preview_row in preview.transactions:
                transaction = preview_row.transaction
                existing = connection.execute(
                    """SELECT * FROM transactions
                       WHERE source_key = ? AND external_id = ?""",
                    (normalized_source, transaction.transaction_id),
                ).fetchone()
                transaction_fingerprint = _transaction_fingerprint(preview_row)
                if existing is not None:
                    if existing["fingerprint"] != transaction_fingerprint:
                        raise ImportConflictError(
                            "A transaction identifier already exists with different data; "
                            "nothing from this file was imported."
                        )
                    duplicate_count += 1
                    connection.execute(
                        "INSERT OR IGNORE INTO import_batch_transactions "
                        "(batch_id, transaction_id) "
                        "VALUES (?, ?)",
                        (batch_id, existing["id"]),
                    )
                    continue

                expected_values = _transaction_values(
                    transaction,
                    batch_id,
                    preview_row,
                    fingerprint=transaction_fingerprint,
                )
                insert_cursor = connection.execute(
                    """INSERT INTO transactions (
                           external_id, source_key, import_batch_id, description,
                           amount_minor_units, currency, movement_type, person,
                           occurred_on, posted_on, category_macro, category_micro,
                           source_fields_json, source_kind, fingerprint
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    expected_values,
                )
                connection.execute(
                    "INSERT INTO import_batch_transactions "
                    "(batch_id, transaction_id) VALUES (?, ?)",
                    (batch_id, insert_cursor.lastrowid),
                )
                imported_count += 1

            connection.commit()
            return ImportResult(batch_id, imported_count, duplicate_count, False)
        except Exception:
            connection.rollback()
            raise

    @_serialized
    def list_imports(self) -> tuple[ImportRecord, ...]:
        rows = self._connection.execute(
            """SELECT id, source_key, content_sha256, imported_at, row_count, raw_filename,
                      person, source_kind
               FROM import_batches ORDER BY id"""
        ).fetchall()
        return tuple(
            ImportRecord(
                batch_id=row["id"],
                source_key=row["source_key"],
                content_sha256=row["content_sha256"],
                imported_at=row["imported_at"],
                row_count=row["row_count"],
                raw_filename=row["raw_filename"],
                person=Person(row["person"]),
                source_kind=SourceKind(row["source_kind"]),
            )
            for row in rows
        )

    @_serialized
    def list_transactions(self) -> tuple[StoredTransaction, ...]:
        rows = self._connection.execute(
            "SELECT t.*, i.invoice_month FROM transactions t "
            "LEFT JOIN card_invoices i ON i.batch_id = t.import_batch_id "
            "ORDER BY t.occurred_on, t.id"
        ).fetchall()
        return tuple(_stored_transaction(row) for row in rows)

    @_serialized
    def list_categories(self) -> tuple[Category, ...]:
        rows = self._connection.execute(
            "SELECT macro, micro FROM categories UNION "
            "SELECT category_macro, category_micro FROM transactions "
            "WHERE category_macro IS NOT NULL AND category_micro IS NOT NULL"
        ).fetchall()
        return tuple(Category(row[0], row[1]) for row in rows)

    @_serialized
    def list_registered_categories(self) -> tuple[tuple[Category, int], ...]:
        rows = self._connection.execute(
            "SELECT c.macro, c.micro, COUNT(t.id) AS usage_count FROM categories c "
            "LEFT JOIN transactions t ON t.category_macro = c.macro "
            "AND t.category_micro = c.micro GROUP BY c.macro, c.micro ORDER BY c.macro, c.micro"
        ).fetchall()
        return tuple((Category(row["macro"], row["micro"]), row["usage_count"]) for row in rows)

    @_serialized
    def add_category(self, category: Category) -> None:
        macro = " ".join(category.macro.split())
        micro = " ".join(category.micro.split())
        key = (macro.casefold(), micro.casefold())
        existing = self.list_categories()
        if any(
            (" ".join(c.macro.split()).casefold(), " ".join(c.micro.split()).casefold()) == key
            for c in existing
        ):
            raise ValueError("Categoria já cadastrada")
        if any(
            " ".join(c.macro.split()).casefold() == key[0] and c.macro != macro for c in existing
        ):
            raise ValueError("Use a grafia da macrocategoria existente")
        with self._connection:
            self._connection.execute(
                "INSERT INTO categories (macro, micro) VALUES (?, ?)", (macro, micro)
            )

    @_serialized
    def delete_category(self, category: Category) -> None:
        with self._connection:
            usage_count = self._connection.execute(
                "SELECT COUNT(*) FROM transactions WHERE category_macro = ? AND category_micro = ?",
                (category.macro, category.micro),
            ).fetchone()[0]
            if usage_count:
                raise ValueError(f"Categoria em uso por {usage_count} movimentação(ões)")
            cursor = self._connection.execute(
                "DELETE FROM categories WHERE macro = ? AND micro = ?",
                (category.macro, category.micro),
            )
            if cursor.rowcount != 1:
                raise KeyError("registered category not found")

    def insert_demo_transactions(self, transactions: Iterable[Transaction]) -> None:
        """Write generated demo rows only; prevents demo rows from mixing with personal data."""
        rows = tuple(transactions)
        if any(row.source_key != "demo-generated" for row in rows):
            raise ValueError("only generated demo transactions can be inserted into demo storage")
        with self._connection:
            for transaction in rows:
                fingerprint = sha256(
                    f"{transaction.transaction_id}:{transaction.amount.minor_units}".encode()
                ).hexdigest()
                self._connection.execute(
                    """INSERT OR IGNORE INTO transactions (
                           external_id, source_key, description, amount_minor_units,
                           currency, movement_type, person, occurred_on, posted_on,
                           category_macro, category_micro, source_fields_json,
                           source_kind, fingerprint
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        transaction.transaction_id,
                        transaction.source_key,
                        transaction.description,
                        transaction.amount.minor_units,
                        transaction.amount.currency,
                        transaction.movement_type.value,
                        transaction.person.value,
                        transaction.occurred_on.isoformat(),
                        transaction.posted_on.isoformat() if transaction.posted_on else None,
                        transaction.category.macro if transaction.category else None,
                        transaction.category.micro if transaction.category else None,
                        "{}",
                        transaction.source_kind.value,
                        fingerprint,
                    ),
                )

    @_serialized
    def list_demo_transactions(self) -> tuple[StoredTransaction, ...]:
        rows = self._connection.execute(
            "SELECT t.*, NULL AS invoice_month FROM transactions t "
            "WHERE t.source_key = 'demo-generated' ORDER BY t.occurred_on, t.id"
        ).fetchall()
        return tuple(_stored_transaction(row) for row in rows)

    @_serialized
    def get_transaction(
        self, external_id: str, *, source_key: str | None = None
    ) -> StoredTransaction:
        if source_key is None:
            rows = self._connection.execute(
                "SELECT t.*, i.invoice_month FROM transactions t "
                "LEFT JOIN card_invoices i ON i.batch_id = t.import_batch_id "
                "WHERE t.external_id = ? ORDER BY t.id LIMIT 2",
                (external_id,),
            ).fetchall()
            if not rows:
                raise KeyError("transaction not found")
            if len(rows) > 1:
                raise ValueError("transaction id is ambiguous; provide source_key")
            row = rows[0]
        else:
            row = self._connection.execute(
                "SELECT t.*, i.invoice_month FROM transactions t "
                "LEFT JOIN card_invoices i ON i.batch_id = t.import_batch_id "
                "WHERE t.source_key = ? AND t.external_id = ?",
                (source_key, external_id),
            ).fetchone()
            if row is None:
                raise KeyError("transaction not found")
        return _stored_transaction(row)

    @_serialized
    def review_movement_type(
        self,
        source_key: str,
        external_id: str,
        movement_type: MovementType,
        *,
        confirm: bool = False,
        category: Category | None = None,
    ) -> StoredTransaction:
        """Change a pending movement's nature only after an explicit user confirmation."""
        if not confirm:
            raise ValueError("movement type changes require confirm=True after human review")
        if movement_type is MovementType.PENDING:
            raise ValueError("use a concrete movement type when confirming a review")
        if category is not None and movement_type is not MovementType.EXPENSE:
            raise ValueError("only expenses can be confirmed with an expense category")
        if category is not None and (not category.macro.strip() or not category.micro.strip()):
            raise ValueError("macro and micro category are required")
        with self._connection:
            cursor = self._connection.execute(
                """UPDATE transactions
                   SET movement_type = ?, category_macro = ?, category_micro = ?, reviewed_at = ?
                   WHERE source_key = ? AND external_id = ? AND movement_type = ?""",
                (
                    movement_type.value,
                    category.macro if category is not None else None,
                    category.micro if category is not None else None,
                    _now(),
                    source_key,
                    external_id,
                    MovementType.PENDING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "transaction missing or no longer pending; no silent overwrite applied"
                )
            self._connection.execute(
                """INSERT INTO transaction_reviews
                       (transaction_id, previous_value, new_value, reviewed_at)
                   SELECT id, ?, ?, ? FROM transactions
                   WHERE source_key = ? AND external_id = ?""",
                (MovementType.PENDING.value, movement_type.value, _now(), source_key, external_id),
            )
            if category is not None:
                self._connection.execute(
                    """INSERT INTO transaction_reviews
                           (transaction_id, previous_value, new_value, reviewed_at)
                       SELECT id, ?, ?, ? FROM transactions
                       WHERE source_key = ? AND external_id = ?""",
                    (
                        "category:pending",
                        f"category:{category.macro}/{category.micro}",
                        _now(),
                        source_key,
                        external_id,
                    ),
                )
        return self.get_transaction(external_id, source_key=source_key)

    @_serialized
    def confirm_category(
        self,
        source_key: str,
        external_id: str,
        category: Category,
        *,
        confirm: bool = False,
    ) -> StoredTransaction:
        if not confirm:
            raise ValueError("category changes require confirm=True after human review")
        if not category.macro.strip() or not category.micro.strip():
            raise ValueError("macro and micro category are required")
        with self._connection:
            row = self._connection.execute(
                "SELECT id, movement_type FROM transactions "
                "WHERE source_key = ? AND external_id = ?",
                (source_key, external_id),
            ).fetchone()
            if row is None:
                raise KeyError("transaction not found")
            if row["movement_type"] != MovementType.EXPENSE.value:
                raise ValueError("only an expense can receive an expense category")
            self._connection.execute(
                "UPDATE transactions SET category_macro = ?, category_micro = ? WHERE id = ?",
                (category.macro, category.micro, row["id"]),
            )
            self._connection.execute(
                """INSERT INTO transaction_reviews
                       (transaction_id, previous_value, new_value, reviewed_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    row["id"],
                    "category:pending",
                    f"category:{category.macro}/{category.micro}",
                    _now(),
                ),
            )
        return self.get_transaction(external_id, source_key=source_key)

    @_serialized
    def review_category(
        self, source_key: str, external_id: str, category: Category
    ) -> StoredTransaction:
        """Mark a human-selected expense category as confirmed and record its audit event."""
        return self.confirm_category(source_key, external_id, category, confirm=True)

    @_serialized
    def correct_classification(
        self,
        source_key: str,
        external_id: str,
        movement_type: MovementType,
        *,
        expected_movement_type: MovementType,
        expected_category: Category | None,
        category: Category | None,
        confirm: bool = False,
    ) -> StoredTransaction:
        """Correct a confirmed movement atomically; retain originals and audit every change."""
        if not confirm:
            raise ValueError("correction requires explicit confirmation")
        if movement_type is MovementType.PENDING or expected_movement_type is MovementType.PENDING:
            raise ValueError("only confirmed movements can be corrected")
        if category is not None and movement_type is not MovementType.EXPENSE:
            raise ValueError("only an expense can have an expense category")
        if movement_type is MovementType.EXPENSE and category is None:
            raise ValueError("choose macro and micro category for the expense")
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT id, movement_type, category_macro, category_micro FROM transactions "
                "WHERE source_key = ? AND external_id = ?",
                (source_key, external_id),
            ).fetchone()
            if row is None:
                raise KeyError("transaction not found")
            current_category = (
                Category(row["category_macro"], row["category_micro"])
                if row["category_macro"] is not None
                else None
            )
            if (
                row["movement_type"] != expected_movement_type.value
                or current_category != expected_category
            ):
                raise ValueError("classification changed; reload before confirming")
            if movement_type is expected_movement_type and category == expected_category:
                raise ValueError("classification has not changed")
            timestamp = _now()
            cursor = self._connection.execute(
                "UPDATE transactions SET movement_type = ?, category_macro = ?, "
                "category_micro = ?, reviewed_at = ? WHERE id = ? AND movement_type = ? "
                "AND category_macro IS ? AND category_micro IS ?",
                (
                    movement_type.value,
                    category.macro if category else None,
                    category.micro if category else None,
                    timestamp,
                    row["id"],
                    expected_movement_type.value,
                    expected_category.macro if expected_category else None,
                    expected_category.micro if expected_category else None,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("classification changed; reload before confirming")
            events = []
            if movement_type is not expected_movement_type:
                events.append((expected_movement_type.value, movement_type.value))
            if category != expected_category:
                events.append(
                    (
                        f"category:{expected_category.macro}/{expected_category.micro}"
                        if expected_category
                        else "category:pending",
                        f"category:{category.macro}/{category.micro}"
                        if category
                        else "category:pending",
                    )
                )
            self._connection.executemany(
                "INSERT INTO transaction_reviews "
                "(transaction_id, previous_value, new_value, reviewed_at) VALUES (?, ?, ?, ?)",
                ((row["id"], before, after, timestamp) for before, after in events),
            )
        return self.get_transaction(external_id, source_key=source_key)

    @_serialized
    def list_reviews(self, source_key: str, external_id: str) -> tuple[tuple[str, str, str], ...]:
        rows = self._connection.execute(
            """SELECT r.previous_value, r.new_value, r.reviewed_at
               FROM transaction_reviews r JOIN transactions t ON t.id = r.transaction_id
               WHERE t.source_key = ? AND t.external_id = ? ORDER BY r.id""",
            (source_key, external_id),
        ).fetchall()
        return tuple((row["previous_value"], row["new_value"], row["reviewed_at"]) for row in rows)

    @_serialized
    def transactions_for_import(self, batch_id: int) -> tuple[StoredTransaction, ...]:
        rows = self._connection.execute(
            """SELECT t.*, i.invoice_month FROM import_batch_transactions link
               JOIN transactions t ON t.id = link.transaction_id
               LEFT JOIN card_invoices i ON i.batch_id = t.import_batch_id
               WHERE link.batch_id = ? ORDER BY t.id""",
            (batch_id,),
        ).fetchall()
        return tuple(_stored_transaction(row) for row in rows)

    @_serialized
    def refresh_payment_candidates(self, *, window_days: int = 5) -> tuple[PaymentCandidate, ...]:
        """Generate exact-amount, nearby-date suggestions; never merge or reclassify rows."""
        if window_days < 0:
            raise ValueError("window_days must not be negative")

        rows = self._connection.execute("SELECT * FROM transactions ORDER BY id").fetchall()
        expenses = [
            row
            for row in rows
            if row["movement_type"] == MovementType.EXPENSE.value
            and row["source_kind"] == SourceKind.CREDIT_CARD.value
        ]
        payments = [
            row
            for row in rows
            if _looks_like_card_payment(row["description"])
            and row["movement_type"] in {MovementType.PENDING.value, MovementType.TRANSFER.value}
            and row["source_kind"] == SourceKind.BANK_ACCOUNT.value
        ]

        with self._connection:
            for payment in payments:
                for expense in expenses:
                    if payment["source_key"] == expense["source_key"]:
                        continue
                    if payment["person"] != expense["person"]:
                        continue
                    if payment["amount_minor_units"] >= 0 or expense["amount_minor_units"] >= 0:
                        continue
                    if abs(payment["amount_minor_units"]) != abs(expense["amount_minor_units"]):
                        continue
                    day_difference = abs(
                        (
                            date.fromisoformat(payment["occurred_on"])
                            - date.fromisoformat(expense["occurred_on"])
                        ).days
                    )
                    if day_difference > window_days:
                        continue
                    self._connection.execute(
                        """INSERT OR IGNORE INTO payment_candidates (
                               expense_transaction_id, payment_transaction_id,
                               amount_minor_units, day_difference, status, created_at
                           ) VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            expense["id"],
                            payment["id"],
                            abs(expense["amount_minor_units"]),
                            day_difference,
                            MatchStatus.PENDING.value,
                            _now(),
                        ),
                    )

        return self.list_payment_candidates()

    @_serialized
    def list_payment_candidates(self) -> tuple[PaymentCandidate, ...]:
        rows = self._connection.execute(
            """SELECT pc.*, expense.external_id AS expense_external_id,
                      payment.external_id AS payment_external_id
               FROM payment_candidates pc
               JOIN transactions expense ON expense.id = pc.expense_transaction_id
               JOIN transactions payment ON payment.id = pc.payment_transaction_id
               ORDER BY pc.id"""
        ).fetchall()
        return tuple(
            PaymentCandidate(
                candidate_id=row["id"],
                expense_transaction_id=row["expense_external_id"],
                payment_transaction_id=row["payment_external_id"],
                amount_minor_units=row["amount_minor_units"],
                day_difference=row["day_difference"],
                status=MatchStatus(row["status"]),
            )
            for row in rows
        )

    @_serialized
    def decide_payment_candidate(
        self,
        candidate_id: int,
        decision: MatchDecision,
    ) -> PaymentCandidate:
        status_by_decision = {
            MatchDecision.ACCEPT: MatchStatus.ACCEPTED,
            MatchDecision.REJECT: MatchStatus.REJECTED,
            MatchDecision.RESET: MatchStatus.PENDING,
        }
        try:
            status = status_by_decision[decision]
        except (KeyError, TypeError) as error:
            raise ValueError("unknown payment-candidate decision") from error

        with self._connection:
            cursor = self._connection.execute(
                "UPDATE payment_candidates SET status = ?, reviewed_at = ? WHERE id = ?",
                (status.value, _now(), candidate_id),
            )
        if cursor.rowcount != 1:
            raise KeyError("payment candidate not found")
        return next(
            candidate
            for candidate in self.list_payment_candidates()
            if candidate.candidate_id == candidate_id
        )

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS import_batches (
                    id INTEGER PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    row_count INTEGER NOT NULL CHECK (row_count >= 0),
                    raw_filename TEXT NOT NULL,
                    person TEXT NOT NULL CHECK (person IN ('self', 'spouse', 'shared')),
                    source_kind TEXT NOT NULL CHECK (
                        source_kind IN ('bank_account', 'credit_card')
                    ),
                    file_fingerprint TEXT NOT NULL,
                    UNIQUE (source_key, content_sha256)
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY,
                    external_id TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    import_batch_id INTEGER REFERENCES import_batches(id),
                    description TEXT NOT NULL,
                    amount_minor_units INTEGER NOT NULL,
                    currency TEXT NOT NULL CHECK (currency = 'BRL'),
                    movement_type TEXT NOT NULL CHECK (
                        movement_type IN ('expense', 'income', 'transfer', 'pending')
                    ),
                    person TEXT NOT NULL CHECK (person IN ('self', 'spouse', 'shared')),
                    occurred_on TEXT NOT NULL,
                    posted_on TEXT,
                    category_macro TEXT,
                    category_micro TEXT,
                    source_fields_json TEXT NOT NULL,
                    reviewed_at TEXT,
                    source_kind TEXT NOT NULL DEFAULT 'bank_account'
                        CHECK (source_kind IN ('bank_account', 'credit_card')),
                    fingerprint TEXT NOT NULL,
                    UNIQUE (source_key, external_id),
                    CHECK (
                        (category_macro IS NULL AND category_micro IS NULL)
                        OR (movement_type = 'expense' AND category_macro IS NOT NULL
                            AND category_micro IS NOT NULL)
                    )
                );

                CREATE TABLE IF NOT EXISTS payment_candidates (
                    id INTEGER PRIMARY KEY,
                    expense_transaction_id INTEGER NOT NULL REFERENCES transactions(id),
                    payment_transaction_id INTEGER NOT NULL REFERENCES transactions(id),
                    amount_minor_units INTEGER NOT NULL CHECK (amount_minor_units >= 0),
                    day_difference INTEGER NOT NULL CHECK (day_difference >= 0),
                    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected')),
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    UNIQUE (expense_transaction_id, payment_transaction_id)
                );

                CREATE TABLE IF NOT EXISTS import_batch_transactions (
                    batch_id INTEGER NOT NULL REFERENCES import_batches(id),
                    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
                    PRIMARY KEY (batch_id, transaction_id)
                );

                CREATE TABLE IF NOT EXISTS transaction_reviews (
                    id INTEGER PRIMARY KEY,
                    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
                    previous_value TEXT NOT NULL,
                    new_value TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS categories (
                    macro TEXT NOT NULL,
                    micro TEXT NOT NULL,
                    PRIMARY KEY (macro, micro)
                );

                CREATE TABLE IF NOT EXISTS card_invoices (
                    batch_id INTEGER PRIMARY KEY REFERENCES import_batches(id),
                    source_key TEXT NOT NULL,
                    invoice_month TEXT NOT NULL,
                    invoice_format TEXT NOT NULL,
                    UNIQUE (source_key, invoice_month)
                );

                CREATE INDEX IF NOT EXISTS idx_transactions_occurred_on
                    ON transactions(occurred_on);
                CREATE INDEX IF NOT EXISTS idx_transactions_movement_type
                    ON transactions(movement_type);
                """
            )
        os.chmod(self.database_path, 0o600)


def _transaction_values(
    transaction: Transaction,
    batch_id: int,
    preview_row: PreviewTransaction,
    *,
    fingerprint: str,
) -> tuple[object, ...]:
    return (
        transaction.transaction_id,
        transaction.source_key,
        batch_id,
        transaction.description,
        transaction.amount.minor_units,
        transaction.amount.currency,
        transaction.movement_type.value,
        transaction.person.value,
        transaction.occurred_on.isoformat(),
        transaction.posted_on.isoformat() if transaction.posted_on else None,
        transaction.category.macro if transaction.category else None,
        transaction.category.micro if transaction.category else None,
        json.dumps(dict(preview_row.source_fields), ensure_ascii=False, separators=(",", ":")),
        transaction.source_kind.value,
        fingerprint,
    )


def _stored_transaction(row: sqlite3.Row) -> StoredTransaction:
    return StoredTransaction(
        transaction_id=row["external_id"],
        source_key=row["source_key"],
        description=row["description"],
        amount_minor_units=row["amount_minor_units"],
        currency=row["currency"],
        movement_type=MovementType(row["movement_type"]),
        person=Person(row["person"]),
        occurred_on=date.fromisoformat(row["occurred_on"]),
        posted_on=date.fromisoformat(row["posted_on"]) if row["posted_on"] else None,
        category=(
            Category(row["category_macro"], row["category_micro"])
            if row["category_macro"] is not None
            else None
        ),
        source_kind=SourceKind(row["source_kind"]),
        invoice_month=row["invoice_month"] if "invoice_month" in row.keys() else None,
    )


def _looks_like_card_payment(description: str) -> bool:
    normalized = " ".join(description.casefold().split())
    return "fatura" in normalized and "pagamento" in normalized


def _transaction_fingerprint(preview_row: PreviewTransaction) -> str:
    transaction = preview_row.transaction
    payload = {
        "external_id": transaction.transaction_id,
        "source_key": transaction.source_key,
        "description": transaction.description,
        "amount_minor_units": transaction.amount.minor_units,
        "currency": transaction.amount.currency,
        "person": transaction.person.value,
        "source_kind": transaction.source_kind.value,
        "occurred_on": transaction.occurred_on.isoformat(),
        "posted_on": transaction.posted_on.isoformat() if transaction.posted_on else None,
        "source_fields": preview_row.source_fields,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def _file_fingerprint(
    preview: ImportPreview,
    *,
    source_key: str,
    content_sha256: str,
) -> str:
    payload = {
        "source_key": source_key,
        "content_sha256": content_sha256,
        "person": _preview_person(preview).value,
        "source_kind": _preview_source_kind(preview).value,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def _preview_person(preview: ImportPreview) -> Person:
    people = {row.transaction.person for row in preview.transactions}
    if len(people) != 1:
        raise ImportRejectedError("A file preview must use exactly one selected person")
    return next(iter(people))


def _preview_source_kind(preview: ImportPreview) -> SourceKind:
    source_kinds = {row.transaction.source_kind for row in preview.transactions}
    if len(source_kinds) != 1:
        raise ImportRejectedError("A file preview must use exactly one source kind")
    return next(iter(source_kinds))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
