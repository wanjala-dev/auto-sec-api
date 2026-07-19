"""Shared send-time faithfulness gate for newsletter dispatch.

Both the human send and the test send run the same check: never email a
figure the newsletter's own data can't support. Extracted here so the two
use cases share one implementation.

No-op when no checker is wired (tests / legacy constructions) or the
newsletter has no metrics corpus (a hand-written ad-hoc send has no ground
truth). Otherwise verifies the rendered body against the persisted metrics
+ reporting period and raises ``NewsletterUnverifiedFiguresError`` unless
the caller explicitly overrides.
"""

from __future__ import annotations

import logging

from components.content.application.ports.faithfulness_check_port import (
    FaithfulnessCheckPort,
)
from components.content.domain.entities.newsletter_entity import NewsletterEntity
from components.content.domain.errors import NewsletterUnverifiedFiguresError
from components.content.domain.services.newsletter_grounding import (
    build_grounding_texts,
    has_grounding,
)

logger = logging.getLogger(__name__)


def enforce_faithfulness_gate(
    *,
    faithfulness_check: FaithfulnessCheckPort | None,
    newsletter: NewsletterEntity,
    html_body: str,
    override_unverified: bool,
) -> None:
    """Raise ``NewsletterUnverifiedFiguresError`` if the copy cites ungrounded figures."""
    if faithfulness_check is None:
        return
    metrics = (newsletter.content_payload or {}).get("metrics") or {}
    if not has_grounding(metrics):
        return

    grounding_texts = build_grounding_texts(
        metrics,
        period_start=newsletter.period_start,
        period_end=newsletter.period_end,
    )
    result = faithfulness_check.check(
        html=html_body, grounding_texts=grounding_texts
    )
    if result.ok:
        return

    if override_unverified:
        logger.warning(
            "newsletter_send_unverified_override newsletter_id=%s "
            "workspace_id=%s unsupported_count=%s",
            newsletter.id,
            newsletter.workspace_id,
            len(result.unsupported_numbers),
        )
        return

    logger.warning(
        "newsletter_send_blocked_unverified newsletter_id=%s "
        "workspace_id=%s unsupported_count=%s",
        newsletter.id,
        newsletter.workspace_id,
        len(result.unsupported_numbers),
    )
    raise NewsletterUnverifiedFiguresError(
        result,
        message=(
            f"Newsletter cites {len(result.unsupported_numbers)} figure(s) "
            f"not found in its data: {', '.join(result.unsupported_numbers)}"
        ),
    )
