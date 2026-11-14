---
name: financial-data
description: Applies practical safeguards for financial calculations and data handling. Use when changing money, balances, transactions, rates, currencies, or financial reporting.
---

# Financial data safeguards

Use these checks when relevant to a task:

- Preserve exact monetary values; avoid binary floating-point for currency calculations when the codebase provides decimal or integer-minor-unit types.
- Make rounding mode and rounding point explicit. Avoid rounding intermediate values unless the product rules require it.
- Keep currency attached to amounts and handle currency conversion as an explicit operation with a known rate and effective time.
- Treat dates, time zones, and period boundaries deliberately, especially for statements, due dates, and reports.
- Validate transaction inputs and preserve invariants when updating balances or derived totals.
- Add or update focused tests for rounding boundaries, zero and negative values, large values, and relevant date/currency cases.
- Follow existing project conventions and domain rules; ask when a financial policy is not specified rather than inventing one.
