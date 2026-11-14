"""In-memory CSV preview for the known Nubank bank-statement format."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from streamline_finance.domain import Money, MovementType, Person, SourceKind, Transaction

DISPLAY_HEADERS = ("Data", "Valor", "Identificador", "Descrição")
SOURCE_HEADER_ALIASES = {"JasData": "Data"}
DATE_PATTERN = re.compile(r"\d{2}/\d{2}/\d{4}\Z")
AMOUNT_PATTERN = re.compile(r"-?\d+(?:\.\d{1,2})?\Z")


class ImportErrorCode(StrEnum):
    EMPTY_FILE = "empty_file"
    HEADER_MISMATCH = "header_mismatch"
    INVALID_CSV = "invalid_csv"
    MALFORMED_ROW = "malformed_row"
    MISSING_REQUIRED_VALUE = "missing_required_value"
    INVALID_DATE = "invalid_date"
    INVALID_AMOUNT = "invalid_amount"


@dataclass(frozen=True, slots=True)
class PreviewError:
    """A safe validation message that identifies location and field, not row values."""

    code: ImportErrorCode
    message: str
    line_number: int | None = None


@dataclass(frozen=True, slots=True)
class PreviewTransaction:
    """A normalized transaction plus the original CSV fields for user review."""

    transaction: Transaction
    source_fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ImportPreview:
    """A read-only import preview; persistence is intentionally not implemented."""

    transactions: tuple[PreviewTransaction, ...]
    errors: tuple[PreviewError, ...]
    skipped_blank_lines: tuple[int, ...]

    @property
    def can_confirm(self) -> bool:
        """Confirmation is safe only when every nonblank row passed validation."""
        return not self.errors and bool(self.transactions)


def preview_nubank_csv(
    content: str | bytes,
    *,
    person: Person,
    source_key: str = "unassigned",
    source_kind: SourceKind = SourceKind.BANK_ACCOUNT,
) -> ImportPreview:
    """Parse CSV in memory without writing, logging, or classifying movement types."""
    if not isinstance(person, Person):
        raise TypeError("person must be selected as a Person value")
    if not source_key.strip():
        raise ValueError("source_key must not be empty")
    if not isinstance(source_kind, SourceKind):
        raise TypeError("source_kind must be a SourceKind value")

    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return ImportPreview(
                transactions=(),
                errors=(
                    PreviewError(
                        ImportErrorCode.INVALID_CSV,
                        "CSV must use UTF-8 encoding; no row values were read.",
                    ),
                ),
                skipped_blank_lines=(),
            )
    elif isinstance(content, str):
        text = content.removeprefix("\ufeff")
    else:
        raise TypeError("content must be CSV text or bytes")

    if not text.strip():
        return ImportPreview(
            transactions=(),
            errors=(PreviewError(ImportErrorCode.EMPTY_FILE, "CSV file is empty."),),
            skipped_blank_lines=(),
        )

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames
        if headers is None:
            return ImportPreview(
                transactions=(),
                errors=(PreviewError(ImportErrorCode.EMPTY_FILE, "CSV has no header row."),),
                skipped_blank_lines=(),
            )
        normalized_headers = [_normalize_header(header) for header in headers]
        if len(normalized_headers) != len(set(normalized_headers)) or any(
            header not in normalized_headers for header in DISPLAY_HEADERS
        ):
            return ImportPreview(
                transactions=(),
                errors=(
                    PreviewError(
                        ImportErrorCode.HEADER_MISMATCH,
                        "CSV columns do not match this export. "
                        f"Required: {', '.join(DISPLAY_HEADERS)}. "
                        "Header spaces and invisible formatting marks are ignored.",
                    ),
                ),
                skipped_blank_lines=(),
            )

        return _parse_rows(
            reader,
            headers,
            normalized_headers,
            person,
            source_key.strip(),
            source_kind,
        )
    except csv.Error:
        return ImportPreview(
            transactions=(),
            errors=(
                PreviewError(
                    ImportErrorCode.INVALID_CSV,
                    "CSV structure is invalid. Check quoting and separators; row values omitted.",
                ),
            ),
            skipped_blank_lines=(),
        )


def _parse_rows(
    reader: csv.DictReader[str],
    headers: list[str],
    normalized_headers: list[str],
    person: Person,
    source_key: str,
    source_kind: SourceKind,
) -> ImportPreview:
    transactions: list[PreviewTransaction] = []
    errors: list[PreviewError] = []
    blank_lines: list[int] = []

    try:
        for row in reader:
            line_number = reader.line_num
            if row.get(None) is not None or any(row.get(header) is None for header in headers):
                errors.append(
                    PreviewError(
                        ImportErrorCode.MALFORMED_ROW,
                        "Row has a different number of columns than its header; "
                        "check the source file.",
                        line_number,
                    )
                )
                continue

            if all(value is None or not value.strip() for value in row.values()):
                blank_lines.append(line_number)
                continue

            normalized_row = {
                normalized: row[original]
                for original, normalized in zip(headers, normalized_headers, strict=True)
            }
            missing = [
                header
                for header in DISPLAY_HEADERS
                if not (normalized_row.get(header) or "").strip()
            ]
            if missing:
                errors.append(
                    PreviewError(
                        ImportErrorCode.MISSING_REQUIRED_VALUE,
                        f"Row is missing required value(s): {', '.join(missing)}.",
                        line_number,
                    )
                )
                continue

            try:
                if not DATE_PATTERN.fullmatch(normalized_row["Data"]):
                    raise ValueError("date must use DD/MM/YYYY")
                occurred_on = datetime.strptime(normalized_row["Data"], "%d/%m/%Y").date()
            except ValueError:
                errors.append(
                    PreviewError(
                        ImportErrorCode.INVALID_DATE,
                        "Date must be a valid calendar date in DD/MM/YYYY format (shown as Data).",
                        line_number,
                    )
                )
                continue

            try:
                if not AMOUNT_PATTERN.fullmatch(normalized_row["Valor"]):
                    raise ValueError("amount must use a decimal point and up to two digits")
                amount = Money.from_decimal(Decimal(normalized_row["Valor"]))
            except (InvalidOperation, ValueError, TypeError):
                errors.append(
                    PreviewError(
                        ImportErrorCode.INVALID_AMOUNT,
                        "Amount must be finite with at most two decimal places (field Valor).",
                        line_number,
                    )
                )
                continue

            transaction = Transaction(
                transaction_id=normalized_row["Identificador"].strip(),
                description=normalized_row["Descrição"].strip(),
                amount=amount,
                movement_type=MovementType.PENDING,
                person=person,
                occurred_on=occurred_on,
                source_key=source_key,
                source_kind=source_kind,
            )
            source_fields = tuple(
                (normalized_header, row[header])
                for header, normalized_header in zip(headers, normalized_headers, strict=True)
            )
            transactions.append(PreviewTransaction(transaction, source_fields))
    except csv.Error:
        errors.append(
            PreviewError(
                ImportErrorCode.INVALID_CSV,
                "CSV structure is invalid near the indicated line; row values omitted.",
                reader.line_num,
            )
        )

    return ImportPreview(tuple(transactions), tuple(errors), tuple(blank_lines))


def _normalize_header(header: str | None) -> str:
    """Normalize known header aliases, Unicode composition, surrounding whitespace and BOMs."""
    if header is None:
        return ""
    normalized = unicodedata.normalize("NFC", header)
    # Remove invisible Unicode format controls anywhere in the header, not only leading BOM.
    cleaned = "".join(
        character for character in normalized if unicodedata.category(character) != "Cf"
    )
    cleaned = cleaned.strip()
    return SOURCE_HEADER_ALIASES.get(cleaned, cleaned)
