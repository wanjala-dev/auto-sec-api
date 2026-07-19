"""Budget recommendation prompt helpers."""

from typing import Iterable, Dict, List


def build_budget_recommendations(
    *,
    year: int,
    ytd_income: float,
    ytd_expenses: float,
    monthly_avg_income: float,
    monthly_avg_expenses: float,
    projected_annual_income: float,
    projected_annual_expenses: float,
    budget_recommendations: Iterable[Dict[str, object]],
    total_recommended_budget: float,
    buffer_percentage: float = 10.0,
) -> str:
    """Compose budget recommendations based on historical financial data."""
    lines: List[str] = []

    lines.append(f"Here's a draft budget for {year} that you can take and edit as needed.")
    lines.append("")

    if ytd_income == 0 and ytd_expenses == 0:
        lines.append("Since you don't have any financial history yet, I've created a basic budget structure that you can customize based on your expected income and expenses.")
        lines.append("")
        lines.append("**Draft Budget Categories:**")
        lines.append("You can add your own categories and amounts. Consider including:")
        lines.append("- Operations & Administration")
        lines.append("- Marketing & Outreach")
        lines.append("- Program Activities")
        lines.append("- Equipment & Supplies")
        lines.append("- Emergency Fund (10-15% of total budget)")
        lines.append("")
        lines.append("**Next Steps:**")
        lines.append("1. Add your expected income sources")
        lines.append("2. Set realistic amounts for each expense category")
        lines.append("3. Review and adjust monthly")
        lines.append("4. Track actual vs. budgeted amounts")
    else:
        lines.append(
            f"Based on your current financial data (${ytd_income:,.2f} income, ${ytd_expenses:,.2f} expenses so far this year), here's what I recommend:"
        )
        lines.append("")

        recommendations = list(budget_recommendations)
        if recommendations:
            lines.append("**Recommended Budget Categories:**")
            for rec in recommendations:
                category = rec.get('category', 'Uncategorized')
                recommended_annual = float(rec.get('recommended_annual', 0.0))
                recommended_monthly = float(rec.get('recommended_monthly', 0.0))
                lines.append(
                    f"- {category}: ${recommended_annual:,.2f} annually (${recommended_monthly:,.2f}/month)"
                )
            lines.append("")

        lines.append(f"**Total Recommended Budget: ${total_recommended_budget:,.2f}**")

        surplus_deficit = projected_annual_income - total_recommended_budget
        lines.append("")
        if surplus_deficit >= 0:
            lines.append(
                f"You’re projected to have a surplus of ${surplus_deficit:,.2f}. Consider setting aside a {buffer_percentage:.0f}% buffer for unexpected costs."
            )
        else:
            lines.append(
                f"You're projected to be short by ${abs(surplus_deficit):,.2f}. Consider reducing discretionary spending or increasing fundraising efforts."
            )
    return "\n".join(lines)
