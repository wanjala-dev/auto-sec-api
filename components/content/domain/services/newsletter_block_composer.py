"""Newsletter block composer — turns AI-output + metrics into a block tree.

Newsletters are rendered on the frontend as a sequence of typed blocks
(hero, KPI cards, text sections, chart, image, CTA). Each block carries
a ``kind`` discriminator and a typed ``payload`` so the editor / viewer
/ email renderer can switch on it.

This module is the bridge between the AI tool output (which today
returns a content_html + sections list) and the structured block format
the FE wants. We synthesize blocks from what's already available; once
the AI tool itself starts emitting a block array directly (planned),
the composer becomes a thin pass-through.

Block schema (versioned for forward-compat):

    {
        "version": 2,
        "blocks": [
            {"kind": "hero",
             "payload": {"title": str, "subtitle": str,
                         "cover_image_url": str | None}},
            {"kind": "hero_overlay",
             "payload": {"image_url": str, "headline": str,
                         "accent_word": str, "align": "left" | "center"}},
            {"kind": "kpi_cards",
             "payload": {"cards": [
                 {"label": str, "value": str, "hint": str},
             ]}},
            {"kind": "text",
             "payload": {"heading": str, "html": str}},
            {"kind": "image",
             "payload": {"url": str, "caption": str | None}},
            {"kind": "image_text_card",
             "payload": {"image_url": str, "title": str,
                         "accent_word": str, "body_html": str,
                         "layout": "image_left" | "image_right"}},
            {"kind": "icon_divider",
             "payload": {"icon": "users" | "heart" | "sparkle",
                         "caption_html": str}},
            {"kind": "chart",
             "payload": {"chart_type": "line", "title": str,
                         "x_label": str, "y_label": str,
                         "series": [{"label": str,
                                      "points": [{"x": str, "y": number}]}]}},
            {"kind": "block_quote",
             "payload": {"quote_html": str, "attribution": str,
                         "role": str}},
            {"kind": "cta",
             "payload": {"label": str, "href": str, "tone": str,
                         "supporting": str}},
            {"kind": "footer",
             "payload": {"tagline": str, "accent_tagline": str,
                         "phone": str, "email": str, "website": str,
                         "copyright": str}},
        ]
    }

A reader that only knows about ``text`` blocks must still render the
whole tree — unknown ``kind`` values get skipped silently. That keeps
the contract additive across releases.

Version history:
  - v1: hero / kpi_cards / text / image / chart / cta
  - v2: adds hero_overlay / image_text_card / icon_divider / footer +
        ``tone="dark"`` variant on cta, ``supporting`` copy on cta
        (front-end PR #234 added the renderers; this composer now emits
        them too).
  - v3: adds block_quote — a standalone pull-quote section (big serif
        quote + attribution). Sections may carry ``pull_quote_html`` /
        ``pull_quote_attribution`` / ``pull_quote_role``; the composer
        emits the quote as its own block right after that section.
        Faithfulness rule: a pull quote must be a VERBATIM quote from
        real workspace content (a recipient update, a testimonial) —
        generation never fabricates one; no quote in the source means
        no block.
  - v4: adds display_heading (giant two-tone report/proposal title:
        {title, accent_word, subtitle}) and stat_row (oversized accent
        figures + captions: {stats: [{value, label}]}) — the editorial
        display blocks the annual-report/proposal design templates use.
        The composer does not auto-emit them; they arrive via design
        templates and (later) kind-aware generation.
  - v5: adds page_header (deck eyebrow row: {left, pill, right}) and
        numbered_sections (proposal list: {sections: [{title,
        body_html}]}) — the proposal-deck vocabulary. Same contract:
        design-template-only, not composer-emitted.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

# v6 (2026-07-13): poster_hero (magazine-cover opener, streetwear-newsletter
# reference) + team_grid (the people behind the work) joined the vocabulary.
# Both are TEMPLATE-authored kinds — the composer never emits them, and
# team_grid is never AI-filled (real humans).
BLOCKS_VERSION = 6


def _format_currency(value: Any) -> str:
    try:
        amount = Decimal(value or 0)
    except (TypeError, ValueError):
        amount = Decimal(0)
    return f"${amount:,.0f}"


def _format_count(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


def _format_period(period_start: datetime.date | None, period_end: datetime.date | None) -> str:
    if not (period_start and period_end):
        return ""
    if period_start.year == period_end.year and period_start.month == period_end.month:
        return period_start.strftime("%B %Y")
    return f"{period_start.strftime('%b %d, %Y')} – {period_end.strftime('%b %d, %Y')}"


def _hero_block(*, workspace_name: str, period_start, period_end, cover_image_url: str | None) -> dict[str, Any]:
    period_label = _format_period(period_start, period_end)
    return {
        "kind": "hero",
        "payload": {
            "title": workspace_name or "Newsletter",
            "subtitle": period_label,
            "cover_image_url": cover_image_url,
        },
    }


def _hero_overlay_block(
    *,
    workspace_name: str,
    period_start,
    period_end,
    image_url: str,
    accent_word: str = "",
) -> dict[str, Any]:
    """Polished hero with a full-bleed image + dark navy overlay card.

    Used when a ``cover_image_url`` is available — it lets the headline
    sit *over* the photo (St. Brigid's-style) instead of below it.
    Without an image the plain ``hero`` block is the right choice; the
    overlay variant assumes there's something to overlay onto.
    """
    period_label = _format_period(period_start, period_end)
    headline = workspace_name or "Newsletter"
    if period_label:
        headline = f"{headline} — {period_label}"
    return {
        "kind": "hero_overlay",
        "payload": {
            "image_url": image_url,
            "headline": headline,
            "accent_word": accent_word or "",
            "align": "left",
        },
    }


def _icon_divider_block(*, icon: str = "users", caption_html: str = "") -> dict[str, Any]:
    """Small centered icon with optional caption — a visual breather.

    The FE accepts ``users``, ``heart``, ``sparkle``, ``star``. Anything
    else falls back to the users glyph on render.
    """
    return {
        "kind": "icon_divider",
        "payload": {
            "icon": icon,
            "caption_html": (caption_html or "").strip(),
        },
    }


def _image_text_card_block(
    *,
    image_url: str,
    title: str,
    body_html: str,
    accent_word: str = "",
    layout: str = "image_left",
) -> dict[str, Any] | None:
    """Two-column card: image on one side, dark text panel on the other.

    Use for spotlight sections — a program update, an impact story,
    anything that benefits from a visual anchor. Returns None if there's
    neither image nor body to render, so callers can pipe spotlight
    sections through unconditionally.
    """
    clean_image_url = (image_url or "").strip()
    clean_body = (body_html or "").strip()
    if not (clean_image_url or clean_body):
        return None
    return {
        "kind": "image_text_card",
        "payload": {
            "image_url": clean_image_url,
            "title": (title or "").strip(),
            "accent_word": (accent_word or "").strip(),
            "body_html": clean_body,
            "layout": layout if layout in ("image_left", "image_right") else "image_left",
        },
    }


def _footer_block(
    *,
    workspace_name: str = "",
    tagline: str = "",
    accent_tagline: str = "",
    phone: str = "",
    email: str = "",
    website: str = "",
    copyright_text: str = "",
) -> dict[str, Any] | None:
    """Dark-navy footer with contact info + merge tokens.

    Returns None when there's no workspace context to render — the
    composer drops it so legacy newsletters (no workspace footer info)
    don't ship an empty dark band. The merge tokens
    (``{{ unsubscribe }}`` etc.) live in the FE renderer; we only
    populate the workspace-specific fields here.
    """
    has_any = any(
        bool((v or "").strip())
        for v in (workspace_name, tagline, accent_tagline, phone, email, website, copyright_text)
    )
    if not has_any:
        return None
    resolved_tagline = (tagline or workspace_name or "").strip()
    resolved_copyright = (copyright_text or "").strip()
    if not resolved_copyright and workspace_name:
        year = datetime.date.today().year
        resolved_copyright = f"© {year} {workspace_name} — All rights reserved"
    return {
        "kind": "footer",
        "payload": {
            "tagline": resolved_tagline,
            "accent_tagline": (accent_tagline or "").strip(),
            "phone": (phone or "").strip(),
            "email": (email or "").strip(),
            "website": (website or "").strip(),
            "copyright": resolved_copyright,
        },
    }


def _block_quote_block(
    *,
    quote_html: str,
    attribution: str = "",
    role: str = "",
) -> dict[str, Any] | None:
    """Standalone pull-quote block — big serif quote + attribution line.

    Returns None when there's no quote to render. Faithfulness: callers
    must only pass VERBATIM quotes that exist in real workspace content
    (a recipient update, a testimonial). Never synthesize one here.
    """
    clean_quote = (quote_html or "").strip()
    if not clean_quote:
        return None
    return {
        "kind": "block_quote",
        "payload": {
            "quote_html": clean_quote,
            "attribution": (attribution or "").strip(),
            "role": (role or "").strip(),
        },
    }


def _kpi_cards_block(metrics: dict[str, Any]) -> dict[str, Any] | None:
    """Build a KPI cards block from the metrics dict the AI tool consumed.

    Returns None if there's nothing meaningful to display — the caller
    drops the block from the tree so we don't render a row of zeros.
    """
    cards: list[dict[str, str]] = []
    donations_total = metrics.get("donations_total") or metrics.get("donations_amount_total")
    if donations_total:
        cards.append(
            {
                "label": "Donations raised",
                "value": _format_currency(donations_total),
                "hint": "This period",
            }
        )
    donations_count = metrics.get("donations_count")
    if donations_count:
        cards.append(
            {
                "label": "Donations",
                "value": _format_count(donations_count),
                "hint": "Gifts received",
            }
        )
    new_supporters = metrics.get("new_supporters") or metrics.get("new_recipients")
    if new_supporters:
        cards.append(
            {
                "label": "New supporters",
                "value": _format_count(new_supporters),
                "hint": "Joined this period",
            }
        )
    recipient_count = metrics.get("recipient_count") or metrics.get("recipients_total")
    if recipient_count:
        cards.append(
            {
                "label": "People served",
                "value": _format_count(recipient_count),
                "hint": "Recipients reached",
            }
        )
    upcoming_events = metrics.get("upcoming_events_count")
    if upcoming_events:
        cards.append(
            {
                "label": "Upcoming events",
                "value": _format_count(upcoming_events),
                "hint": "Coming up",
            }
        )
    if not cards:
        return None
    return {"kind": "kpi_cards", "payload": {"cards": cards}}


def _section_blocks(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert AI-emitted sections to either text blocks or image_text_cards.

    A section with ``spotlight_image_url`` becomes the polished 2-col
    card (image + dark text panel). Sections without an image fall
    through to the plain text block — same shape v1 emitted. This means
    today's writing-agent output works unchanged; once the AI tool
    starts attaching ``spotlight_image_url`` to a section, the FE picks
    up the richer rendering automatically.

    Optional per-section keys consumed:
        spotlight_image_url    — promotes the section to image_text_card
        accent_word            — serif italic accent word inside the title
        spotlight_layout       — "image_left" (default) or "image_right"
        pull_quote_html        — a VERBATIM quote from real workspace
                                 content; emitted as its own block_quote
                                 right after the section (v3)
        pull_quote_attribution — who said it (name)
        pull_quote_role        — their relationship (e.g. "Monthly donor")
    """
    blocks: list[dict[str, Any]] = []
    for index, section in enumerate(sections or []):
        heading = (section.get("heading") or "").strip()
        body_html = (section.get("body_html") or section.get("html") or "").strip()
        if not (heading or body_html):
            continue
        pull_quote = _block_quote_block(
            quote_html=section.get("pull_quote_html", "") or "",
            attribution=section.get("pull_quote_attribution", "") or "",
            role=section.get("pull_quote_role", "") or "",
        )
        spotlight_image_url = (section.get("spotlight_image_url") or "").strip()
        if spotlight_image_url:
            # Alternate image_left / image_right across spotlight sections
            # so a sequence of program updates doesn't feel monotonous.
            layout = section.get("spotlight_layout") or ("image_left" if index % 2 == 0 else "image_right")
            card = _image_text_card_block(
                image_url=spotlight_image_url,
                title=heading,
                body_html=body_html,
                accent_word=section.get("accent_word", "") or "",
                layout=layout,
            )
            if card is not None:
                blocks.append(card)
                if pull_quote is not None:
                    blocks.append(pull_quote)
                continue
        blocks.append(
            {
                "kind": "text",
                "payload": {"heading": heading, "html": body_html},
            }
        )
        if pull_quote is not None:
            blocks.append(pull_quote)
    return blocks


def _text_blocks_from_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backwards-compatible alias retained for callers that imported the
    v1 name directly. New code should use ``_section_blocks``."""
    return _section_blocks(sections)


def _fallback_text_block(content_html: str) -> dict[str, Any] | None:
    """When the AI tool returned ``content_html`` without ``sections`` we
    still want at least one text block in the tree so the viewer renders
    something. The whole HTML lands in a single section with no heading.
    """
    if not (content_html or "").strip():
        return None
    return {
        "kind": "text",
        "payload": {"heading": "", "html": content_html},
    }


def _cta_block(
    workspace_donate_url: str | None,
    *,
    label: str = "Support our work",
    tone: str = "dark",
    supporting: str = "",
) -> dict[str, Any] | None:
    """CTA pill block.

    ``tone`` defaults to ``dark`` — the polished pill (navy fill, white
    text, all-caps label) the St. Brigid sample uses for "SEE OUR WORK"
    / "GET INVOLVED". Pass ``tone="primary"`` for the legacy emerald/
    amber gradient.
    """
    if not workspace_donate_url:
        return None
    return {
        "kind": "cta",
        "payload": {
            "label": label,
            "href": workspace_donate_url,
            "tone": tone,
            "supporting": supporting,
        },
    }


def _image_block(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pass-through for image blocks the AI tool emits.

    Today the synthesizer doesn't generate images on its own (no source
    of relevance-ranked cover photos). The schema is here so future AI
    output that includes ``image_blocks`` lands in the tree.
    """
    if not payload:
        return None
    url = (payload.get("url") or "").strip()
    if not url:
        return None
    return {
        "kind": "image",
        "payload": {
            "url": url,
            "caption": payload.get("caption", "") or "",
        },
    }


def _chart_block_from_series(
    *,
    title: str,
    series: list[dict[str, Any]],
    chart_type: str = "line",
    x_label: str = "",
    y_label: str = "",
) -> dict[str, Any] | None:
    """Build a chart block from prepared series data.

    Caller resolves the actual data (e.g. donations bucketed by week);
    this just wraps the shape the FE expects. Returns None when there
    are no points to plot — the renderer should not show an empty axis.
    """
    if not series:
        return None
    non_empty = [s for s in series if isinstance(s, dict) and s.get("points") and len(s["points"]) > 0]
    if not non_empty:
        return None
    return {
        "kind": "chart",
        "payload": {
            "chart_type": chart_type,
            "title": title,
            "x_label": x_label,
            "y_label": y_label,
            "series": non_empty,
        },
    }


def compose(
    *,
    workspace_name: str,
    period_start: datetime.date | None,
    period_end: datetime.date | None,
    metrics: dict[str, Any],
    sections: list[dict[str, Any]],
    content_html: str = "",
    cover_image_url: str | None = None,
    workspace_donate_url: str | None = None,
    chart_series: dict[str, Any] | None = None,
    image_blocks: list[dict[str, Any]] | None = None,
    hero_accent_word: str = "",
    cta_label: str = "Support our work",
    cta_supporting: str = "",
    cta_tone: str = "dark",
    footer_email: str = "",
    footer_phone: str = "",
    footer_website: str = "",
    footer_tagline: str = "",
    footer_accent_tagline: str = "",
    icon_divider_caption_html: str = "",
) -> dict[str, Any]:
    """Compose the full block tree for a newsletter draft.

    Returns the versioned ``{"version": ..., "blocks": [...]}`` envelope.
    Callers store this as ``Newsletter.content_payload['layout']`` so the
    FE editor can read it and render the visual blocks while still
    falling back to ``content_html`` when ``layout`` is missing (legacy
    newsletters drafted before this composer existed).

    The v2 sequence:
        hero_overlay (or hero if no cover image)
        kpi_cards
        chart
        icon_divider (when at least one of the above two landed)
        text / image_text_card per section
        image
        cta (dark tone by default)
        footer

    Each block is dropped silently when its source data is empty — a
    workspace with no donations, no chart data, no contact info ends up
    with a smaller but still coherent layout.

    ``chart_series`` shape — when provided, embeds a chart block right
    after the KPI cards:

        {
            "title": str,
            "x_label": str,
            "y_label": str,
            "chart_type": "line",
            "series": [{"label": str, "points": [{"x": str, "y": num}]}]
        }

    ``image_blocks`` — list of ``{"url": str, "caption": str}`` payloads,
    appended between text and CTA blocks. Empty list / None skips.

    ``hero_accent_word`` — serif italic accent appended to the hero
    headline (e.g. "gratitude and *hope*"). Only rendered by the
    hero_overlay variant; harmless when the plain hero is used.

    ``footer_*`` — workspace contact info threaded into the footer
    block. Missing fields render as gaps; the footer drops entirely
    when none are provided.
    """
    blocks: list[dict[str, Any]] = []
    if cover_image_url:
        blocks.append(
            _hero_overlay_block(
                workspace_name=workspace_name,
                period_start=period_start,
                period_end=period_end,
                image_url=cover_image_url,
                accent_word=hero_accent_word,
            )
        )
    else:
        blocks.append(
            _hero_block(
                workspace_name=workspace_name,
                period_start=period_start,
                period_end=period_end,
                cover_image_url=None,
            )
        )
    kpi = _kpi_cards_block(metrics or {})
    if kpi is not None:
        blocks.append(kpi)

    if chart_series:
        chart = _chart_block_from_series(
            title=chart_series.get("title", "") or "",
            series=chart_series.get("series") or [],
            chart_type=chart_series.get("chart_type", "line") or "line",
            x_label=chart_series.get("x_label", "") or "",
            y_label=chart_series.get("y_label", "") or "",
        )
        if chart is not None:
            blocks.append(chart)

    # Optional visual breather between the metrics and the copy. Emit ONLY when
    # an explicit caption is supplied — a bare auto-inserted icon (a lone heart
    # glyph) reads as clutter, so it is no longer emitted by default.
    if (icon_divider_caption_html or "").strip():
        blocks.append(_icon_divider_block(icon="users", caption_html=icon_divider_caption_html))

    text_blocks = _section_blocks(sections or [])
    if text_blocks:
        blocks.extend(text_blocks)
    else:
        fallback = _fallback_text_block(content_html or "")
        if fallback is not None:
            blocks.append(fallback)

    for image_payload in image_blocks or []:
        image = _image_block(image_payload)
        if image is not None:
            blocks.append(image)

    cta = _cta_block(
        workspace_donate_url,
        label=cta_label,
        tone=cta_tone,
        supporting=cta_supporting,
    )
    if cta is not None:
        blocks.append(cta)

    footer = _footer_block(
        workspace_name=workspace_name,
        tagline=footer_tagline,
        accent_tagline=footer_accent_tagline,
        phone=footer_phone,
        email=footer_email,
        website=footer_website,
    )
    if footer is not None:
        blocks.append(footer)

    return {"version": BLOCKS_VERSION, "blocks": blocks}
