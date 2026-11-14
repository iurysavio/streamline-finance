"""Read confirmed, historical expense-description mappings from a workbook."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from openpyxl import load_workbook

from streamline_finance.categorization import CategorizationRule
from streamline_finance.domain import Category


@dataclass(frozen=True, slots=True)
class HistoricalRules:
    rules: tuple[CategorizationRule, ...]
    skipped_without_description: int

    @property
    def rule_count(self) -> int:
        return len(self.rules)


class HistoricalRuleError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def load_expense_rules(
    content: bytes,
    *,
    confirm_column_mapping: bool,
    sheet_name: str = "Entrada",
) -> HistoricalRules:
    """Load the established provisional map only after a caller explicitly opts in.

    Mapping used (still subject to user confirmation): Tipo de Fluxo -> macro,
    Fluxo -> micro, Classificação == Despesa, Observação -> exact description.
    The workbook is read from bytes; no file path, database, logs, or external service involved.
    """
    if not confirm_column_mapping:
        raise HistoricalRuleError(
            "mapping_not_confirmed",
            "Confirm the workbook column meanings before deriving category rules.",
        )
    if not isinstance(content, bytes):
        raise TypeError("workbook content must be provided as bytes")

    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception as error:
        raise HistoricalRuleError("invalid_workbook", "Workbook could not be read.") from error

    if sheet_name not in workbook.sheetnames:
        workbook.close()
        raise HistoricalRuleError("missing_sheet", "The requested workbook sheet was not found.")

    sheet = workbook[sheet_name]
    header_row_index, header_values = _find_header_row(sheet)
    required = ("Fluxo", "Tipo de Fluxo", "Classificação", "Observação")
    missing = tuple(name for name in required if name not in header_values)
    if missing:
        workbook.close()
        raise HistoricalRuleError(
            "missing_columns",
            f"Required workbook columns are missing: {', '.join(missing)}.",
        )

    column_indexes = {name: header_values.index(name) for name in required}
    rules: dict[str, CategorizationRule] = {}
    skipped = 0
    try:
        for row_number, row in enumerate(
            sheet.iter_rows(min_row=header_row_index + 1, values_only=True),
            start=header_row_index + 1,
        ):
            classification = _cell_text(row, column_indexes["Classificação"])
            if _normalize_label(classification) != "despesa":
                continue

            description = _cell_text(row, column_indexes["Observação"])
            macro = _cell_text(row, column_indexes["Tipo de Fluxo"])
            micro = _cell_text(row, column_indexes["Fluxo"])
            if not description:
                skipped += 1
                continue
            if not macro or not micro:
                # Don't include the actual workbook contents in the exception.
                raise HistoricalRuleError(
                    "incomplete_category",
                    f"An expense row near row {row_number} has an incomplete category pair.",
                )

            key = _normalize_description(description)
            category = Category(macro=macro, micro=micro)
            if key in rules and rules[key].category != category:
                raise HistoricalRuleError(
                    "ambiguous_description",
                    f"An expense description near row {row_number} maps to conflicting categories.",
                )
            if key not in rules:
                identifier = sha256(
                    f"{row_number}\0{description}\0{macro}\0{micro}".encode()
                ).hexdigest()[:16]
                rules[key] = CategorizationRule(
                    rule_id=f"history-{identifier}",
                    description=description,
                    category=category,
                )
    finally:
        workbook.close()

    return HistoricalRules(tuple(rules.values()), skipped)


def _find_header_row(sheet) -> tuple[int, tuple[str, ...]]:
    strongest: tuple[int, tuple[str, ...]] | None = None
    for row_index, row in enumerate(sheet.iter_rows(min_row=1, max_row=10, values_only=True), 1):
        values = tuple(_cell_text(row, index) for index in range(len(row)))
        if "Fluxo" in values and "Classificação" in values:
            return row_index, values
        if strongest is None and any(
            value in {"Data", "Valor", "Detalhe", "Descrição"} for value in values
        ):
            strongest = (row_index, values)
    if strongest is not None:
        return strongest
    raise HistoricalRuleError("missing_header", "Could not locate the expense header row.")


def _cell_text(row: tuple[object, ...], index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def _normalize_label(value: str) -> str:
    return " ".join(value.casefold().split())


def _normalize_description(value: str) -> str:
    return " ".join(value.casefold().split())
