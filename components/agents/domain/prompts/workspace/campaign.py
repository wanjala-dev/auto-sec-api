"""Campaign-related prompt helpers."""

from typing import Iterable, List, Optional


def build_campaign_description(
    *,
    workspace_name: str,
    base_story: str,
    goal_amount: Optional[float],
    donations_count_window: int,
    donations_sum_window: float,
    sponsored_recipients_total: int,
    recent_highlights: Optional[Iterable[str]] = None,
) -> str:
    """Compose a donor-facing campaign description with goal and highlights."""
    highlights = list(recent_highlights or [])
    goal_line = (
        f"Our goal: raise {goal_amount:,.2f} to accelerate our impact."
        if goal_amount is not None
        else "Join us to help us reach more people."
    )

    parts: List[str] = []
    parts.append(f"{workspace_name or 'Our workspace'} is on a mission to create lasting change.")
    if base_story:
        parts.append(base_story)
    parts.append(goal_line)
    parts.append("")
    parts.append("Why your support matters:")
    parts.append(
        f"- In the past 30 days, we received {donations_count_window} donation(s) totaling {donations_sum_window:,.2f}."
    )
    parts.append(f"- Recipients sponsored to date: {sponsored_recipients_total}.")

    if highlights:
        parts.append("")
        parts.append("Recent highlights:")
        for highlight in highlights:
            parts.append(f"- {highlight}")

    parts.append("")
    parts.append(
        "Every contribution—large or small—moves us closer to our goal. If you can't give today, please share this campaign with friends and family."
    )
    parts.append("Thank you for your support!")
    return "\n".join(parts)
