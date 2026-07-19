"""Financial prompt helpers for workspace reporting."""

from typing import Iterable, Dict, List


def build_financial_report(
    *,
    window_label: str,
    income_total: float,
    expenses_total: float,
    net_total: float,
    donations_total: float,
    budget_count: int,
    top_expense_categories: Iterable[Dict[str, float]] = (),
) -> str:
    """Compose a simple financial report block."""
    lines: List[str] = []
    lines.append(f"Financial Report ({window_label})\n")
    lines.append(f"Income: {income_total:.2f}")
    lines.append(f"Expenses: {expenses_total:.2f}")
    lines.append(f"Net: {net_total:.2f}")
    lines.append(f"Donations received: {donations_total:.2f}")
    lines.append(f"Budgets configured: {budget_count}")

    breakdown = list(top_expense_categories or [])
    if breakdown:
        lines.append("\nTop Expense Categories:")
        for row in breakdown:
            cat = row.get('category', 'Uncategorized')
            total = float(row.get('total', 0.0))
            lines.append(f"- {cat}: {total:.2f}")
    return "\n".join(lines)
