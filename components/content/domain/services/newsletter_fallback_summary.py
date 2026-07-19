"""Deterministic grounded-summary fallback for newsletters (SEE-174).

Pure domain service — NO Django, NO ORM, NO LLM. When the grounded
deep-planner path returns no parseable prose (LLM 5xx, unparseable
output, or the agent system isn't configured), the newsletter use case
MUST NOT persist an empty shell (the audited defect: branded header +
chart + footer, zero prose). Instead it persists *this* — a clearly
sourced summary built straight from the enriched period metrics.

Every figure in the produced copy comes verbatim from the metrics dict,
so the output passes the faithfulness verifier (SEE-171) by construction:
nothing is invented, only what the ledger / records hold is stated.

The summary is honest about thin periods. When the workspace had no
donations, new recipients, events, or active programs in the window, the
body says so plainly ("a quieter period") and the caller marks the row
``thin_data=True`` so the editor surfaces a "thin data for this period"
banner rather than a blank draft. It is never an empty body.
"""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def build(
    *,
    workspace_name: str,
    period_start: datetime.date | None,
    period_end: datetime.date | None,
    metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a grounded summary draft from period metrics.

    Returns a dict shaped like the AI adapter's payload so the use case
    can treat it uniformly:

        {
            "title": str,
            "content_html": str,        # always non-empty
            "sections": [{"heading": str, "html": str}, ...],
            "thin": bool,               # True when the period had no activity
            "grounding_texts": [str],   # source strings for the verifier
        }
    """

    metrics = metrics or {}
    org = (workspace_name or "").strip() or "our organization"
    period_label = _period_label(period_start, period_end)

    sections: list[dict[str, str]] = []
    # Seed the grounding corpus with the period + org so the period year
    # (e.g. "2026") and the org name in the copy are supported facts for
    # the faithfulness verifier — not flagged as invented.
    grounding: list[str] = [org]
    if period_label:
        grounding.append(period_label)
    if period_start:
        grounding.append(period_start.isoformat())
    if period_end:
        grounding.append(period_end.isoformat())

    donations_count = _int(metrics.get("donations_count"))
    donations_total = _money_display(metrics.get("donations_total"), metrics)
    top_donors = metrics.get("top_donors") or []
    new_recipients = _int(metrics.get("new_recipients"))
    new_recipient_names = metrics.get("new_recipient_names") or []
    recipient_count = _int(metrics.get("recipient_count"))
    recent_events = metrics.get("recent_events") or []
    upcoming_events = metrics.get("upcoming_events") or []
    active_projects = metrics.get("active_projects") or []
    delta_pct = metrics.get("donations_delta_pct")

    has_activity = bool(
        donations_count
        or new_recipients
        or recent_events
        or upcoming_events
        or active_projects
    )

    # ── intro ────────────────────────────────────────────────────────────
    if period_label:
        intro = (
            f"Here is a look at what happened at {org} during {period_label}."
        )
    else:
        intro = f"Here is a recent update from {org}."
    if not has_activity:
        intro += (
            " This was a quieter period — the figures below reflect the "
            "activity we have on record so far."
        )
    sections.append({"heading": "Welcome", "html": _p(intro)})

    # ── giving highlights ────────────────────────────────────────────────
    if donations_count:
        gift_word = "gift" if donations_count == 1 else "gifts"
        line = (
            f"We received {donations_count} {gift_word}"
            + (f" totaling {donations_total}" if donations_total else "")
            + " this period."
        )
        grounding.append(f"Donations count: {donations_count}")
        if donations_total:
            grounding.append(f"Donations total: {metrics.get('donations_total')}")
        if isinstance(delta_pct, (int, float)) and delta_pct:
            direction = "up" if delta_pct > 0 else "down"
            line += f" That is {direction} {abs(int(delta_pct))}% from the previous period."
            grounding.append(f"Donation change: {abs(int(delta_pct))}%")
        donor_clause = _donor_clause(top_donors, grounding)
        if donor_clause:
            line += " " + donor_clause
        sections.append({"heading": "Giving highlights", "html": _p(line)})

    # ── people served ────────────────────────────────────────────────────
    people_lines: list[str] = []
    if new_recipients:
        person_word = "person" if new_recipients == 1 else "people"
        ppl = f"We welcomed {new_recipients} new {person_word} into our programs"
        names = [str(n) for n in new_recipient_names if str(n).strip()]
        if names:
            ppl += f", including {_join_names(names)}"
            grounding.extend(f"New recipient: {n}" for n in names)
        people_lines.append(ppl + ".")
        grounding.append(f"New recipients: {new_recipients}")
    if recipient_count:
        people_lines.append(
            f"We are now supporting {recipient_count} people in total."
        )
        grounding.append(f"Total recipients: {recipient_count}")
    if people_lines:
        sections.append(
            {"heading": "People we serve", "html": _p(" ".join(people_lines))}
        )

    # ── programs ─────────────────────────────────────────────────────────
    if active_projects:
        titles = [str(p.get("title") or "").strip() for p in active_projects]
        titles = [t for t in titles if t]
        if titles:
            grounding.extend(f"Program: {t}" for t in titles)
            sections.append(
                {
                    "heading": "Programs underway",
                    "html": _p(
                        "Our active programs include "
                        + _join_names(titles)
                        + "."
                    ),
                }
            )

    # ── events ───────────────────────────────────────────────────────────
    event_lines: list[str] = []
    if recent_events:
        for evt in recent_events:
            title = str(evt.get("title") or "").strip()
            if not title:
                continue
            grounding.append(f"Event: {title}")
            raised = evt.get("raised")
            if raised:
                grounding.append(f"Event raised: {raised}")
                event_lines.append(
                    f"{title} brought our community together and raised "
                    f"{_money_str(raised, metrics)}."
                )
            else:
                event_lines.append(f"{title} brought our community together.")
    if upcoming_events:
        up_titles = [str(e.get("title") or "").strip() for e in upcoming_events]
        up_titles = [t for t in up_titles if t]
        if up_titles:
            grounding.extend(f"Upcoming event: {t}" for t in up_titles)
            event_lines.append(
                "Coming up next: " + _join_names(up_titles) + "."
            )
    if event_lines:
        sections.append({"heading": "Events", "html": _p(" ".join(event_lines))})

    # ── thank-you + CTA (always present) ─────────────────────────────────
    sections.append(
        {
            "heading": "Thank you",
            "html": _p(
                "Thank you for standing with "
                f"{org}. Every bit of support moves this work forward, and "
                "we are grateful to have you alongside us."
            ),
        }
    )
    sections.append(
        {
            "heading": "Get involved",
            "html": _p(
                "Want to do more? Share this update with a friend or make a "
                "gift today — your support keeps these programs going."
            ),
        }
    )

    title = (
        f"{org} — {period_label}" if period_label else f"{org} Newsletter"
    )
    content_html = "".join(
        f"<h3>{s['heading']}</h3>{s['html']}" for s in sections
    )

    return {
        "title": title,
        "content_html": content_html,
        "sections": sections,
        "thin": not has_activity,
        "grounding_texts": grounding,
    }


# ── helpers ─────────────────────────────────────────────────────────────────


def _donor_clause(top_donors: list[Any], grounding: list[str]) -> str:
    cleaned = [
        d
        for d in top_donors
        if isinstance(d, dict) and str(d.get("name") or "").strip()
    ]
    if not cleaned:
        return ""
    lead = cleaned[0]
    name = str(lead.get("name")).strip()
    grounding.append(f"Top donor: {name}")
    amount = lead.get("amount")
    if amount:
        grounding.append(f"Top donor amount: {amount}")
        return f"We are especially grateful to {name} for a gift of {amount}."
    return f"We are especially grateful to {name} for their generosity."


def _period_label(
    period_start: datetime.date | None, period_end: datetime.date | None
) -> str:
    """Human-readable period — "June 2026" for a single month, otherwise a
    "Jun 1 – Jun 30, 2026" range. Empty when either bound is missing."""
    if not (period_start and period_end):
        return ""
    if (
        period_start.year == period_end.year
        and period_start.month == period_end.month
    ):
        return period_start.strftime("%B %Y")
    return (
        f"{period_start.strftime('%b %d, %Y')} – "
        f"{period_end.strftime('%b %d, %Y')}"
    )


def _join_names(names: list[str]) -> str:
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _p(text: str) -> str:
    return f"<p>{text.strip()}</p>"


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _currency_symbol(metrics: dict[str, Any]) -> str:
    code = str((metrics or {}).get("currency") or "").upper()
    return {"USD": "$", "EUR": "€", "GBP": "£", "NGN": "₦", "INR": "₹"}.get(
        code, ""
    )


def _money_display(value: Any, metrics: dict[str, Any]) -> str:
    """Render a money figure as ``$50,000`` (or ``50,000 KES``).

    Returns "" when the value is missing/zero so callers can omit the
    clause entirely rather than print "$0".
    """
    if not value:
        return ""
    return _money_str(value, metrics)


def _money_str(value: Any, metrics: dict[str, Any]) -> str:
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    grouped = f"{dec:,.0f}" if dec == dec.to_integral_value() else f"{dec:,.2f}"
    symbol = _currency_symbol(metrics)
    if symbol:
        return f"{symbol}{grouped}"
    code = str((metrics or {}).get("currency") or "").upper()
    return f"{grouped} {code}".strip()
