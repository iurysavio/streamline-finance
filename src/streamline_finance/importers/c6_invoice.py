"""Read a C6 card CSV into a non-persistent preview with original fields intact."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from streamline_finance.domain import Money, MovementType, Person, SourceKind, Transaction
from streamline_finance.importers.nubank import (
    ImportErrorCode,
    ImportPreview,
    PreviewError,
    PreviewTransaction,
)

HEADERS = (
    "Data de Compra",
    "Nome no Cartão",
    "Final do Cartão",
    "Categoria",
    "Descrição",
    "Parcela",
    "Valor (em US$)",
    "Cotação (em R$)",
    "Valor (em R$)",
)


def preview_c6_invoice(
    content: bytes, *, person: Person, source_key: str = "unassigned"
) -> ImportPreview:
    """Preview only; this format has no transaction ID and is not safe to persist yet."""
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
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=";", strict=True)
    rows: list[PreviewTransaction] = []
    errors: list[PreviewError] = []
    skipped: list[int] = []
    try:
        headers = next(reader, [])
        if tuple(value.strip() for value in headers) != HEADERS:
            return ImportPreview(
                (),
                (
                    PreviewError(
                        ImportErrorCode.HEADER_MISMATCH, "Cabeçalhos da fatura C6 não reconhecidos."
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
            if len(row) != len(HEADERS):
                errors.append(
                    PreviewError(ImportErrorCode.MALFORMED_ROW, "Número de colunas inválido.", line)
                )
                continue
            try:
                if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", row[0].strip()):
                    raise ValueError
                occurred_on = datetime.strptime(row[0].strip(), "%d/%m/%Y").date()
            except ValueError:
                errors.append(
                    PreviewError(ImportErrorCode.INVALID_DATE, "Data de compra inválida.", line)
                )
                continue
            try:
                value = row[8].strip()
                if not re.fullmatch(r"-?\d+(?:\.\d{1,2})?", value):
                    raise ValueError
                amount = Money.from_decimal(-Decimal(value))
            except (ValueError, InvalidOperation):
                errors.append(
                    PreviewError(ImportErrorCode.INVALID_AMOUNT, "Valor em reais inválido.", line)
                )
                continue
            if not row[4].strip():
                errors.append(
                    PreviewError(ImportErrorCode.MISSING_REQUIRED_VALUE, "Descrição ausente.", line)
                )
                continue
            transaction = Transaction(
                transaction_id=f"c6-preview-{digest}-{line}",
                description=row[4].strip(),
                amount=amount,
                movement_type=MovementType.PENDING,
                person=person,
                occurred_on=occurred_on,
                source_key=source_key.strip(),
                source_kind=SourceKind.CREDIT_CARD,
            )
            rows.append(PreviewTransaction(transaction, tuple(zip(HEADERS, row, strict=True))))
    except csv.Error:
        errors.append(
            PreviewError(ImportErrorCode.INVALID_CSV, "Estrutura CSV inválida.", reader.line_num)
        )
    return ImportPreview(tuple(rows), tuple(errors), tuple(skipped), invoice_format="c6_invoice")
