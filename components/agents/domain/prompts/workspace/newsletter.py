"""Newsletter prompt builders for workspace communications."""

from typing import Iterable, List, Optional


def build_sponsor_newsletter(
    *,
    window_label: str,
    donations_count: int,
    donations_sum: float,
    new_sponsorships: int,
    sponsored_recipients_total: int,
    recent_action_titles: Optional[Iterable[str]] = None,
    greeting: str = "Dear Sponsor,",
    closing: str = "With gratitude,\nThe Team",
) -> str:
    """Compose a concise sponsor newsletter text block."""
    titles = list(recent_action_titles or [])

    lines: List[str] = []
    lines.append(f"{greeting}\n")
    lines.append(
        f"Thank you for your continued support! Here’s a quick update from the {window_label}:\n"
    )
    lines.append(f"- Donations received: {donations_count} (total {donations_sum:.2f})")
    lines.append(f"- New sponsorships: {new_sponsorships}")
    lines.append(f"- Recipients sponsored to date: {sponsored_recipients_total}\n")

    if titles:
        lines.append("Recent Highlights:")
        for title in titles:
            lines.append(f"- {title}")
        lines.append("")

    lines.append(
        "We are grateful for your partnership. Together, we’re making a real difference.\n"
    )
    lines.append(closing)
    return "\n".join(lines)
