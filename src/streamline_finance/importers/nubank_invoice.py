"""Read Nubank card CSV as a non-persistent preview."""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from streamline_finance.domain import Money, MovementType, Person, SourceKind, Transaction
from streamline_finance.importers.nubank import (
    ImportErrorCode,
    ImportPreview,
    PreviewError,
    PreviewTransaction,
)


def preview_nubank_invoice(
    content: bytes, *, person: Person, source_key: str = "unassigned"
) -> ImportPreview:
    """Interpret verified CSV signs; each movement still requires human review."""
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if not isinstance(person, Person) or not source_key.strip():
        raise ValueError("select a valid person and source")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ImportPreview(
            (), (PreviewError(ImportErrorCode.INVALID_CSV, "CSV deve usar UTF-8."),), ()
        )
    if not text.strip():
        return ImportPreview((), (PreviewError(ImportErrorCode.EMPTY_FILE, "CSV vazio."),), ())
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    rows: list[PreviewTransaction] = []
    errors: list[PreviewError] = []
    skipped: list[int] = []
    try:
        headers = next(reader, [])
        if tuple(value.strip() for value in headers) != ("date", "title", "amount"):
            return ImportPreview(
                (),
                (
                    PreviewError(
                        ImportErrorCode.HEADER_MISMATCH,
                        "Cabeçalhos da fatura Nubank não reconhecidos.",
                    ),
                ),
                (),
            )
        digest = sha256(content).hexdigest()
        for row in reader:
            line = reader.line_num
            if not row or all(not value.strip() for value in row):
                skipped.append(line)
                continue
            if len(row) != 3:
                errors.append(
                    PreviewError(ImportErrorCode.MALFORMED_ROW, "Número de colunas inválido.", line)
                )
                continue
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[0].strip()):
                    raise ValueError
                occurred_on = date.fromisoformat(row[0].strip())
            except ValueError:
                errors.append(
                    PreviewError(ImportErrorCode.INVALID_DATE, "Data de compra inválida.", line)
                )
                continue
            try:
                value = row[2].strip()
                if not re.fullmatch(r"-?\s*\d+(?:,\d{1,2})?", value):
                    raise ValueError
                amount = Money.from_decimal(-Decimal(value.replace(" ", "").replace(",", ".")))
            except (ValueError, InvalidOperation):
                errors.append(
                    PreviewError(ImportErrorCode.INVALID_AMOUNT, "Valor em reais inválido.", line)
                )
                continue
            if not row[1].strip():
                errors.append(
                    PreviewError(ImportErrorCode.MISSING_REQUIRED_VALUE, "Descrição ausente.", line)
                )
                continue
            transaction = Transaction(
                transaction_id=f"nubank-preview-{digest}-{line}",
                description=row[1].strip(),
                amount=amount,
                movement_type=MovementType.PENDING,
                person=person,
                occurred_on=occurred_on,
                source_key=source_key.strip(),
                source_kind=SourceKind.CREDIT_CARD,
            )
            rows.append(
                PreviewTransaction(
                    transaction, tuple(zip(("date", "title", "amount"), row, strict=True))
                )
            )
    except csv.Error:
        errors.append(
            PreviewError(ImportErrorCode.INVALID_CSV, "Estrutura CSV inválida.", reader.line_num)
        )
    return ImportPreview(
        tuple(rows), tuple(errors), tuple(skipped), invoice_format="nubank_invoice"
    )
