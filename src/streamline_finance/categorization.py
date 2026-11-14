"""Explainable exact-match category rules; no fuzzy or learned classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from streamline_finance.domain import Category, MovementType, Transaction


class CategorizationStatus(StrEnum):
    SUGGESTED = "suggested"
    NEEDS_REVIEW = "needs_review"
    AMBIGUOUS = "ambiguous"
    NOT_APPLICABLE = "not_applicable"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class CategorizationRule:
    """An explicit exact description-to-category mapping with a stable ID."""

    rule_id: str
    description: str
    category: Category

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be empty")
        if not self.description.strip():
            raise ValueError("rule description must not be empty")


@dataclass(frozen=True, slots=True)
class CategorizationResult:
    """A suggestion or review state, preserving its original rule provenance."""

    status: CategorizationStatus
    suggested_category: Category | None
    confirmed_category: Category | None
    matched_rule_ids: tuple[str, ...]
    explanation: str

    def confirm(self, category: Category) -> CategorizationResult:
        """Record a human confirmation/correction without replacing the suggestion."""
        if self.status is CategorizationStatus.NOT_APPLICABLE:
            raise ValueError("non-expense movements cannot be assigned expense categories")
        return CategorizationResult(
            status=CategorizationStatus.CONFIRMED,
            suggested_category=self.suggested_category,
            confirmed_category=category,
            matched_rule_ids=self.matched_rule_ids,
            explanation=self.explanation,
        )


def suggest_category(
    transaction: Transaction,
    rules: list[CategorizationRule] | tuple[CategorizationRule, ...],
) -> CategorizationResult:
    """Suggest only from exact normalized descriptions; collisions need review."""
    if transaction.movement_type is not MovementType.EXPENSE:
        return CategorizationResult(
            status=CategorizationStatus.NOT_APPLICABLE,
            suggested_category=None,
            confirmed_category=None,
            matched_rule_ids=(),
            explanation="Movement is not an expense; expense categorization was skipped.",
        )

    normalized_description = _normalize_description(transaction.description)
    matches = tuple(
        rule for rule in rules if _normalize_description(rule.description) == normalized_description
    )
    rule_ids = tuple(sorted({rule.rule_id for rule in matches}))
    categories = {rule.category for rule in matches}

    if not matches:
        return CategorizationResult(
            status=CategorizationStatus.NEEDS_REVIEW,
            suggested_category=None,
            confirmed_category=None,
            matched_rule_ids=(),
            explanation="No exact description rule matched; manual review is required.",
        )

    if len(categories) > 1:
        return CategorizationResult(
            status=CategorizationStatus.AMBIGUOUS,
            suggested_category=None,
            confirmed_category=None,
            matched_rule_ids=rule_ids,
            explanation="Matching rules disagree; manual review is required.",
        )

    category = next(iter(categories))
    return CategorizationResult(
        status=CategorizationStatus.SUGGESTED,
        suggested_category=category,
        confirmed_category=None,
        matched_rule_ids=rule_ids,
        explanation=f"Exact normalized description matched rule(s): {', '.join(rule_ids)}.",
    )


def _normalize_description(description: str) -> str:
    """Ignore case and repeated whitespace only; keep accents and punctuation significant."""
    return " ".join(description.casefold().split())
