"""Resolve ``{{placeholders}}`` inside a design template's block-tree layout.

Extracted from the newsletter controller (task #19) so BOTH apply paths —
"Use this template" on a newsletter AND compose-a-draft-from-a-template —
share one resolver. Pure orchestration: stdlib only, the actual token
substitution goes through the injected resolver (the same
``TemplatePlaceholderResolver`` port the body_html path uses).
"""

from __future__ import annotations

import copy
from typing import Any

# Block-tree text fields that may carry ``{{placeholders}}`` to resolve when a
# design template is applied to a workspace. Image URLs / hrefs are left as-is.
LAYOUT_TEXT_FIELDS = (
    "html",
    "body_html",
    "caption_html",
    "supporting",
    "headline",
    "title",
    "subtitle",
    "tagline",
    "accent_tagline",
    # block_quote (v3) + display blocks (v4)
    "quote_html",
    "attribution",
    "role",
    "accent_word",
    # page_header (v5)
    "left",
    "pill",
    "right",
    # poster_hero (v6) — eyebrows/notes may carry {{workspace_name}};
    # headline/accent_word are already covered above.
    "eyebrow_left",
    "eyebrow_right",
    "note_left",
    "note_right",
)

# Text keys that may carry tokens inside nested collection entries.
_CARD_KEYS = ("label", "value", "hint")
_ITEM_KEYS = ("title", "body", "label")
_EVENT_KEYS = ("title", "location", "label", "date")
_STAT_KEYS = ("value", "label", "hint")
_SECTION_KEYS = ("title", "body_html")


def resolve_layout_placeholders(layout: Any, resolver: Any, workspace_id: Any, donate_url: str = "") -> dict[str, Any]:
    """Deep-copy a design template's block-tree layout and resolve workspace
    placeholders in its text fields, so a picked design fills with real data.

    ``resolver`` may be ``None`` (best-effort) — then text tokens are left
    verbatim, but the ``{{donate_url}}`` substitution still runs. Per-block
    failures are swallowed so one bad token can't abort the whole apply.

    A CTA block's ``href`` of ``{{donate_url}}`` is replaced with the workspace
    donate link; when there's no donate link the href becomes empty, and the
    CTA renderer drops the block (no broken "Get Involved" link). The same
    href substitution applies to nested action links in the ``items`` (volunteer
    CTA grid) and ``events`` (events list) collections.
    """

    def _sub_href(d: dict) -> None:
        href = d.get("href")
        if isinstance(href, str) and "{{donate_url}}" in href:
            d["href"] = href.replace("{{donate_url}}", donate_url)

    def _resolve_text(d: dict, keys) -> None:
        if resolver is None:
            return
        for key in keys:
            value = d.get(key)
            if isinstance(value, str) and "{{" in value:
                try:
                    d[key] = resolver.resolve(body_html=value, workspace_id=workspace_id)
                except Exception:
                    pass

    resolved = copy.deepcopy(layout) if isinstance(layout, dict) else {}
    for block in resolved.get("blocks", []) or []:
        payload = block.get("payload") if isinstance(block, dict) else None
        if not isinstance(payload, dict):
            continue
        # Donate-link substitution on the block's own action href — runs
        # independent of the text resolver (a missing resolver must not skip it).
        _sub_href(payload)
        _resolve_text(payload, LAYOUT_TEXT_FIELDS)
        # Nested collections: KPI cards + stat rows carry tokenized figures;
        # volunteer grid items + events carry copy and optional donate links.
        for entry in payload.get("cards", []) or []:
            if isinstance(entry, dict):
                _resolve_text(entry, _CARD_KEYS)
        for entry in payload.get("stats", []) or []:
            if isinstance(entry, dict):
                _resolve_text(entry, _STAT_KEYS)
        for entry in payload.get("sections", []) or []:
            if isinstance(entry, dict):
                _resolve_text(entry, _SECTION_KEYS)
        for entry in payload.get("items", []) or []:
            if isinstance(entry, dict):
                _sub_href(entry)
                _resolve_text(entry, _ITEM_KEYS)
        for entry in payload.get("events", []) or []:
            if isinstance(entry, dict):
                _sub_href(entry)
                _resolve_text(entry, _EVENT_KEYS)
    return resolved
