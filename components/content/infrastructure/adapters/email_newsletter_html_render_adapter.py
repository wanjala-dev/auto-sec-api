"""Email-safe HTML renderer for the newsletter block tree.

Implements ``NewsletterHtmlRenderPort`` in pure Python — no Django template, no
new dependency, fully unit-testable. It mirrors the frontend
``NewsletterBlocksView`` block vocabulary (hero / hero_overlay / kpi_cards /
chart / text / image / image_text_card / icon_divider / cta / footer) but emits
**email-safe** markup: a centered fixed-width table, inline styles only, no
flexbox/grid (two-column blocks use nested tables), on a warm "envelope"
background — modeled on the St. Brigid's Outreach reference Henry approved.

This one renderer is the single source of truth for what subscribers see: the
send path, the PDF export, and the in-app preview iframe all call it, so they
can never drift. Per-recipient merge tokens (``{{unsubscribe_url}}`` etc.) are
emitted intact for the dispatch adapter to substitute per recipient.

Why pure Python over a Django template: email HTML is deeply nested tables with
inline styles — far more legible as composable string builders than as a
template, and testable with zero framework. A future ``MjmlNewsletter…`` or
Django-template adapter can replace this behind the port with no caller change
(``/templates`` skill §3a.D).
"""

from __future__ import annotations

from html import escape
from typing import Any

from components.content.application.ports.newsletter_html_render_port import (
    NewsletterHtmlRenderPort,
)

# ── Palette (mirrors the Tailwind classes in NewsletterBlocksView) ──────────
_ENVELOPE_BG = "#f7f1e8"  # warm peach/cream page background
_CARD_BG = "#ffffff"
_NAVY = "#0f172a"  # slate-900 — overlay cards, footer, dark CTA
_NAVY_SOFT = "#1e293b"  # slate-800
_EMERALD = "#047857"  # emerald-700 — eyebrow / accents
_EMERALD_FILL = "#d1fae5"  # emerald-100
_AMBER_ACCENT = "#f59e0b"  # serif italic accent on light
_AMBER_ON_DARK = "#fcd34d"  # serif italic accent on navy
_TEXT = "#1f2937"  # gray-800
_MUTED = "#6b7280"  # gray-500
_BORDER = "#e5e7eb"  # gray-200
_LIGHT_ON_DARK = "#e2e8f0"  # slate-200
_SERIF = "Georgia, 'Times New Roman', serif"
_SANS = "Arial, 'Helvetica Neue', Helvetica, sans-serif"
_CONTENT_WIDTH = 600

# The unsubscribe href uses the token the DISPATCH adapter substitutes
# (``{{unsubscribe_url}}``), NOT the frontend's display-only ``{{ unsubscribe }}``
# — so the sent email's footer link actually resolves per recipient. Emitting it
# here also suppresses the dispatch adapter's defensive auto-footer (it only
# appends when the token is absent), avoiding a double unsubscribe link.
_UNSUBSCRIBE_TOKEN = "{{unsubscribe_url}}"


def _esc(value: Any) -> str:
    return escape(str(value or ""), quote=True)


class EmailNewsletterHtmlRenderAdapter(NewsletterHtmlRenderPort):
    """Render a newsletter layout block tree into a complete HTML email."""

    def render(
        self,
        *,
        layout: dict[str, Any] | None,
        fallback_html: str = "",
        context: dict[str, Any] | None = None,
    ) -> str:
        ctx = context or {}
        # Non-email documents (a designed DRAFT's PDF export) must not carry
        # email-only chrome — currently just the footer's unsubscribe link.
        self._document_only = bool(ctx.get("document_only"))
        blocks = []
        if isinstance(layout, dict):
            raw = layout.get("blocks")
            if isinstance(raw, list):
                blocks = raw

        if blocks:
            inner = "".join(self._render_block(b) for b in blocks if isinstance(b, dict))
        else:
            # True legacy row (no block tree) — wrap the prose in a single card
            # so even pre-composer newsletters render on the envelope chrome.
            inner = self._legacy_card(fallback_html)

        return self._document(inner, preheader=ctx.get("preheader", ""))

    # ── document shell ──────────────────────────────────────────────────
    def _document(self, inner_html: str, *, preheader: str = "") -> str:
        preheader_span = ""
        if preheader:
            preheader_span = (
                '<span style="display:none!important;visibility:hidden;opacity:0;'
                'height:0;width:0;overflow:hidden;mso-hide:all;">'
                f"{_esc(preheader)}</span>"
            )
        return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta http-equiv="X-UA-Compatible" content="IE=edge" />
</head>
<body style="margin:0;padding:0;background-color:{_ENVELOPE_BG};">
{preheader_span}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" \
style="background-color:{_ENVELOPE_BG};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="{_CONTENT_WIDTH}" cellpadding="0" cellspacing="0" border="0" \
style="width:{_CONTENT_WIDTH}px;max-width:100%;font-family:{_SANS};">
{inner_html}
</table>
</td></tr>
</table>
</body>
</html>"""

    def _row(self, content: str, *, padding: str = "0 0 20px 0") -> str:
        """Wrap a block in a full-width spacing row inside the content table."""
        return f'<tr><td style="padding:{padding};">{content}</td></tr>'

    # ── block dispatch ──────────────────────────────────────────────────
    def _render_block(self, block: dict[str, Any]) -> str:
        kind = block.get("kind")
        payload = block.get("payload") or {}
        renderer = {
            "hero": self._hero,
            "hero_overlay": self._hero_overlay,
            "kpi_cards": self._kpi_cards,
            "text": self._text,
            "image": self._image,
            "image_text_card": self._image_text_card,
            "spotlight_person": self._spotlight_person,
            "block_quote": self._block_quote,
            "display_heading": self._display_heading,
            "poster_hero": self._poster_hero,
            "team_grid": self._team_grid,
            "stat_row": self._stat_row,
            "page_header": self._page_header,
            "numbered_sections": self._numbered_sections,
            "volunteer_cta_grid": self._volunteer_cta_grid,
            "events_list": self._events_list,
            "icon_divider": self._icon_divider,
            "cta": self._cta,
            "footer": self._footer,
            # ``chart`` is intentionally omitted: email clients can't run the
            # Chart.js canvas, and a broken/blank chart reads worse than none.
            # The KPI cards carry the same figures. A static-image chart is a
            # future enhancement (render server-side to PNG, embed as <img>).
        }.get(kind)
        if renderer is None:
            return ""  # unknown / chart — skip silently (additive schema)
        return renderer(payload)

    # ── hero ────────────────────────────────────────────────────────────
    def _hero(self, p: dict[str, Any]) -> str:
        title = _esc(p.get("title") or "Workspace update")
        subtitle = _esc(p.get("subtitle") or "")
        cover = (p.get("cover_image_url") or "").strip()
        img = (
            f'<tr><td><img src="{_esc(cover)}" width="{_CONTENT_WIDTH}" '
            f'alt="" style="display:block;width:100%;max-width:{_CONTENT_WIDTH}px;'
            'height:auto;border-top-left-radius:18px;border-top-right-radius:18px;" /></td></tr>'
            if cover
            else ""
        )
        sub = f'<p style="margin:6px 0 0;font-size:14px;color:{_MUTED};">{subtitle}</p>' if subtitle else ""
        body = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:18px;">'
            f"{img}"
            '<tr><td align="center" style="padding:32px 24px;">'
            f'<p style="margin:0;font-size:11px;font-weight:bold;letter-spacing:3px;'
            f'text-transform:uppercase;color:{_EMERALD};">Newsletter</p>'
            f'<h1 style="margin:8px 0 0;font-size:28px;line-height:1.2;color:#111827;">{title}</h1>'
            f"{sub}"
            "</td></tr></table>"
        )
        return self._row(body)

    # ── hero overlay (image + navy headline card) ───────────────────────
    def _hero_overlay(self, p: dict[str, Any]) -> str:
        image_url = (p.get("image_url") or "").strip()
        headline = _esc(p.get("headline") or "A message of gratitude")
        accent = _esc(p.get("accent_word") or "")
        accent_html = (
            f'&nbsp;<span style="font-family:{_SERIF};font-style:italic;'
            f'font-weight:normal;color:{_AMBER_ON_DARK};">{accent}</span>'
            if accent
            else ""
        )
        # Email-safe: image on top, navy headline band directly beneath, pulled
        # up just enough to sit low over the photo's bottom edge (true CSS
        # overlay isn't reliable across clients). The band spans the FULL width
        # of the image — no side inset — so it reads as a caption bar, and only
        # a small negative margin so the title sits low on the image rather than
        # riding high up it. Keeps the dramatic photo + navy-card + serif-accent
        # feel of the reference.
        img = (
            f'<tr><td><img src="{_esc(image_url)}" width="{_CONTENT_WIDTH}" alt="" '
            f'style="display:block;width:100%;max-width:{_CONTENT_WIDTH}px;height:auto;'
            'border-top-left-radius:18px;border-top-right-radius:18px;" /></td></tr>'
            if image_url
            else ""
        )
        band_radius = (
            "border-bottom-left-radius:18px;border-bottom-right-radius:18px;" if image_url else "border-radius:18px;"
        )
        card = (
            '<tr><td style="padding:0;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background-color:{_NAVY};{"margin-top:-16px;" if image_url else ""}{band_radius}">'
            '<tr><td style="padding:32px 28px;">'
            f'<p style="margin:0;font-size:30px;line-height:1.25;font-weight:bold;color:#ffffff;">'
            f"{headline}{accent_html}</p>"
            "</td></tr></table></td></tr>"
        )
        body = f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{img}{card}</table>'
        return self._row(body)

    # ── kpi cards ───────────────────────────────────────────────────────
    def _kpi_cards(self, p: dict[str, Any]) -> str:
        cards = [c for c in (p.get("cards") or []) if isinstance(c, dict)]
        if not cards:
            return ""
        # Two columns per row for reliable email rendering.
        cells = []
        for c in cards:
            label = _esc(c.get("label"))
            value = _esc(c.get("value"))
            hint = _esc(c.get("hint"))
            hint_html = f'<p style="margin:4px 0 0;font-size:11px;color:{_MUTED};">{hint}</p>' if hint else ""
            cells.append(
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:14px;">'
                '<tr><td style="padding:18px 16px;">'
                f'<p style="margin:0;font-size:11px;font-weight:bold;letter-spacing:1px;'
                f'text-transform:uppercase;color:{_MUTED};">{label}</p>'
                f'<p style="margin:6px 0 0;font-size:24px;font-weight:bold;color:#111827;">{value}</p>'
                f"{hint_html}"
                "</td></tr></table>"
            )
        rows = []
        for i in range(0, len(cells), 2):
            left = cells[i]
            right = cells[i + 1] if i + 1 < len(cells) else ""
            right_td = (
                f'<td width="50%" valign="top" style="padding:0 0 12px 6px;">{right}</td>'
                if right
                else '<td width="50%">&nbsp;</td>'
            )
            rows.append(f'<tr><td width="50%" valign="top" style="padding:0 6px 12px 0;">{left}</td>{right_td}</tr>')
        body = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            + "".join(rows)
            + "</table>"
        )
        return self._row(body)

    # ── text ────────────────────────────────────────────────────────────
    def _text(self, p: dict[str, Any]) -> str:
        heading = _esc(p.get("heading"))
        html = (p.get("html") or "").strip()  # sanitized at save — emit as-is
        if not heading and not html:
            return ""
        heading_html = f'<h2 style="margin:0 0 12px;font-size:20px;color:#111827;">{heading}</h2>' if heading else ""
        body_html = f'<div style="font-size:15px;line-height:1.6;color:{_TEXT};">{html}</div>' if html else ""
        return self._row(f"{heading_html}{body_html}")

    # ── image ───────────────────────────────────────────────────────────
    def _image(self, p: dict[str, Any]) -> str:
        url = (p.get("url") or "").strip()
        if not url:
            return ""
        caption = _esc(p.get("caption"))
        caption_html = (
            f'<p style="margin:0;padding:10px 14px;font-size:12px;font-style:italic;color:{_MUTED};">{caption}</p>'
            if caption
            else ""
        )
        body = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:14px;overflow:hidden;">'
            f'<tr><td><img src="{_esc(url)}" width="{_CONTENT_WIDTH}" alt="{caption}" '
            'style="display:block;width:100%;max-width:100%;height:auto;" /></td></tr>'
            f"<tr><td>{caption_html}</td></tr></table>"
        )
        return self._row(body)

    # ── image + text card (two-column) ──────────────────────────────────
    def _image_text_card(self, p: dict[str, Any]) -> str:
        image_url = (p.get("image_url") or "").strip()
        title = _esc(p.get("title") or "A Word of Thanks")
        accent = _esc(p.get("accent_word") or "")
        body_html = (p.get("body_html") or "").strip()
        image_first = (p.get("layout") or "image_left") != "image_right"
        accent_html = (
            f'&nbsp;<span style="font-family:{_SERIF};font-style:italic;'
            f'font-weight:normal;color:{_AMBER_ON_DARK};">{accent}</span>'
            if accent
            else ""
        )
        img_cell = (
            f'<td width="45%" valign="middle" style="background-color:{_EMERALD_FILL};">'
            + (
                f'<img src="{_esc(image_url)}" width="270" alt="" '
                'style="display:block;width:100%;max-width:270px;height:auto;" />'
                if image_url
                else "&nbsp;"
            )
            + "</td>"
        )
        text_cell = (
            f'<td width="55%" valign="middle" style="background-color:{_NAVY};padding:24px 22px;">'
            f'<h3 style="margin:0;font-size:22px;line-height:1.3;color:#ffffff;">{title}{accent_html}</h3>'
            + (
                f'<div style="margin-top:10px;font-size:14px;line-height:1.6;color:{_LIGHT_ON_DARK};">{body_html}</div>'
                if body_html
                else ""
            )
            + "</td>"
        )
        order = (img_cell + text_cell) if image_first else (text_cell + img_cell)
        body = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="border-radius:16px;overflow:hidden;">'
            f"<tr>{order}</tr></table>"
        )
        return self._row(body)

    # ── page header (eyebrow row: org / centre pill / doc-type) ─────────
    def _page_header(self, p: dict[str, Any]) -> str:
        """Deck-style eyebrow row from the proposal references: org name on
        the left, an optional pill in the centre (a year, an issue number),
        the document type on the right."""
        left = _esc(p.get("left"))
        pill = _esc(p.get("pill"))
        right = _esc(p.get("right"))
        if not (left or pill or right):
            return ""
        pill_html = (
            f'<span style="display:inline-block;border:1px solid {_BORDER};'
            f"border-radius:999px;padding:2px 12px;font-size:10px;"
            f'letter-spacing:1px;color:{_MUTED};">{pill}</span>'
            if pill
            else "&nbsp;"
        )
        style = f"font-size:10px;font-weight:bold;letter-spacing:2px;text-transform:uppercase;color:{_MUTED};"
        body = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            "<tr>"
            f'<td width="40%" align="left" style="{style}">{left}</td>'
            f'<td width="20%" align="center">{pill_html}</td>'
            f'<td width="40%" align="right" style="{style}">{right}</td>'
            "</tr></table>"
        )
        return self._row(body, padding="0 0 10px 0")

    # ── numbered sections (proposal service/section list) ───────────────
    def _numbered_sections(self, p: dict[str, Any]) -> str:
        """Proposal-deck numbered list: an accent number, a bold heading,
        and a short body per section."""
        sections = [
            s for s in (p.get("sections") or []) if isinstance(s, dict) and (s.get("title") or s.get("body_html"))
        ]
        if not sections:
            return ""
        rows = "".join(
            "<tr>"
            f'<td width="52" valign="top" style="padding:14px 0;">'
            f'<p style="margin:0;font-size:22px;font-weight:800;color:{_AMBER_ACCENT};">'
            f"{index:02d}</p></td>"
            f'<td valign="top" style="padding:14px 0;border-bottom:1px solid {_BORDER};">'
            f'<p style="margin:0;font-size:14px;font-weight:bold;letter-spacing:0.5px;'
            f'text-transform:uppercase;color:#111827;">{_esc(s.get("title"))}</p>'
            + (
                f'<div style="margin-top:6px;font-size:13px;line-height:1.6;color:{_TEXT};">'
                f"{(s.get('body_html') or '').strip()}</div>"
                if (s.get("body_html") or "").strip()
                else ""
            )
            + "</td></tr>"
            for index, s in enumerate(sections[:8], start=1)
        )
        body = f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>'
        return self._row(body)

    # ── display heading (giant two-tone title, no image) ────────────────
    def _display_heading(self, p: dict[str, Any]) -> str:
        """Report/proposal-style display title: big bold heading with an
        accent-coloured word/line and an optional subtitle. The imageless
        counterpart of the hero blocks (annual-report reference)."""
        title = _esc(p.get("title"))
        accent_word = _esc(p.get("accent_word"))
        subtitle = _esc(p.get("subtitle"))
        if not (title or accent_word):
            return ""
        accent_html = f' <span style="color:{_AMBER_ACCENT};">{accent_word}</span>' if accent_word else ""
        subtitle_html = f'<p style="margin:10px 0 0;font-size:13px;color:{_MUTED};">{subtitle}</p>' if subtitle else ""
        body = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            '<tr><td style="padding:14px 4px 6px;">'
            f'<h1 style="margin:0;font-size:34px;line-height:1.1;font-weight:800;'
            f'color:#111827;">{title}{accent_html}</h1>'
            f"{subtitle_html}"
            "</td></tr></table>"
        )
        return self._row(body)

    # ── poster hero (v6 — streetwear-newsletter reference) ──────────────
    def _poster_hero(self, p: dict[str, Any]) -> str:
        """Magazine-cover opener: eyebrow labels, an OVERSIZED two-tone
        headline, the photo on an accent panel, bold side notes. Email
        clients can't do the web view's overlap, so the email version
        stacks: eyebrows → headline → image on the accent panel → notes."""
        headline = _esc(p.get("headline"))
        accent_word = _esc(p.get("accent_word"))
        image_url = (p.get("image_url") or "").strip()
        if not (headline or image_url):
            return ""
        eyebrow_left = _esc(p.get("eyebrow_left"))
        eyebrow_right = _esc(p.get("eyebrow_right"))
        note_left = _esc(p.get("note_left"))
        note_right = _esc(p.get("note_right"))

        eyebrows = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#374151;">{eyebrow_left}</td>'
            f'<td align="right" style="font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#374151;">{eyebrow_right}</td>'
            "</tr></table>"
            if (eyebrow_left or eyebrow_right)
            else ""
        )
        accent_html = f' <span style="color:{_EMERALD};">{accent_word}</span>' if accent_word else ""
        heading_html = (
            f'<h1 style="margin:12px 0 0;font-size:44px;line-height:0.95;font-weight:800;'
            f'letter-spacing:-1px;color:#111827;">{headline}{accent_html}</h1>'
            if headline
            else ""
        )
        img_html = (
            f'<img src="{image_url}" alt="" width="100%" '
            'style="display:block;width:100%;height:auto;border-radius:10px;" />'
            if image_url
            else ""
        )
        notes = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="font-size:11px;font-weight:700;text-transform:uppercase;color:#ffffff;">{note_left}</td>'
            f'<td align="right" style="font-size:11px;font-weight:700;text-transform:uppercase;color:#ffffff;">{note_right}</td>'
            "</tr></table>"
            if (note_left or note_right)
            else ""
        )
        body = (
            f"{eyebrows}{heading_html}"
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td style="background:{_EMERALD};border-radius:12px;padding:18px;">'
            f"{img_html}{notes}"
            "</td></tr></table>"
        )
        return self._row(body)

    # ── team grid (v6 — charity-report reference) ───────────────────────
    def _team_grid(self, p: dict[str, Any]) -> str:
        """The people behind the work — photo (or initial), name, role, in a
        row-of-three grid. Members are real humans: never AI-filled."""
        members = [m for m in (p.get("members") or []) if isinstance(m, dict) and (m.get("name") or m.get("image_url"))]
        if not members:
            return ""
        title = _esc(p.get("title"))
        title_html = (
            f'<h2 style="margin:0 0 14px;font-size:22px;font-weight:800;color:#111827;">{title}</h2>' if title else ""
        )
        cells = []
        for member in members:
            name = _esc(member.get("name"))
            role = _esc(member.get("role"))
            image_url = (member.get("image_url") or "").strip()
            photo = (
                f'<img src="{image_url}" alt="{name}" width="72" height="72" '
                'style="display:block;margin:0 auto;width:72px;height:72px;border-radius:50%;" />'
                if image_url
                else (
                    f'<div style="width:72px;height:72px;line-height:72px;border-radius:50%;'
                    f"background:{_EMERALD};color:#ffffff;font-size:24px;font-weight:700;"
                    f'text-align:center;margin:0 auto;">{(name or "?")[:1].upper()}</div>'
                )
            )
            role_html = f'<p style="margin:2px 0 0;font-size:11px;color:{_MUTED};">{role}</p>' if role else ""
            cells.append(
                '<td width="33%" align="center" valign="top" style="padding:10px 6px;">'
                f"{photo}"
                f'<p style="margin:8px 0 0;font-size:13px;font-weight:600;color:#111827;">{name}</p>'
                f"{role_html}"
                "</td>"
            )
        rows_html = ""
        for i in range(0, len(cells), 3):
            rows_html += "<tr>" + "".join(cells[i : i + 3]) + "</tr>"
        body = (
            f"{title_html}"
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f"{rows_html}"
            "</table>"
        )
        return self._row(body)

    # ── stat row (giant accent figures + captions) ──────────────────────
    def _stat_row(self, p: dict[str, Any]) -> str:
        """Annual-report style stats: oversized accent-coloured values with
        small captions underneath, side by side. The display counterpart of
        the kpi_cards block (cards → dashboard; stat_row → editorial)."""
        stats = [s for s in (p.get("stats") or []) if isinstance(s, dict) and s.get("value")]
        if not stats:
            return ""
        width = int(100 / len(stats))
        cells = "".join(
            f'<td width="{width}%" align="center" valign="top" style="padding:14px 8px;">'
            f'<p style="margin:0;font-size:32px;font-weight:800;color:{_AMBER_ACCENT};">{_esc(s.get("value"))}</p>'
            f'<p style="margin:6px 0 0;font-size:11px;letter-spacing:1px;text-transform:uppercase;'
            f'color:{_MUTED};">{_esc(s.get("label"))}</p>'
            "</td>"
            for s in stats[:4]
        )
        body = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:18px;">'
            f"<tr>{cells}</tr></table>"
        )
        return self._row(body)

    # ── block quote (standalone pull quote) ─────────────────────────────
    def _block_quote(self, p: dict[str, Any]) -> str:
        """Centered serif pull quote — big amber quote mark, italic quote,
        attribution + role underneath. Returns "" when there's no quote.
        """
        quote_html = (p.get("quote_html") or "").strip()
        if not quote_html:
            return ""
        attribution = _esc(p.get("attribution"))
        role = _esc(p.get("role"))
        attribution_html = ""
        if attribution:
            role_part = f'<span style="font-weight:normal;color:{_MUTED};"> · {role}</span>' if role else ""
            attribution_html = (
                f'<p style="margin:14px 0 0;font-size:13px;font-weight:bold;'
                f'letter-spacing:1px;text-transform:uppercase;color:{_EMERALD};">'
                f"&mdash; {attribution}{role_part}</p>"
            )
        body = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:18px;">'
            '<tr><td align="center" style="padding:30px 36px;">'
            f'<p style="margin:0;font-family:{_SERIF};font-size:44px;line-height:0.6;'
            f'color:{_AMBER_ACCENT};">&ldquo;</p>'
            f'<div style="margin-top:10px;font-family:{_SERIF};font-style:italic;'
            f'font-size:18px;line-height:1.6;color:{_TEXT};">{quote_html}</div>'
            f"{attribution_html}"
            "</td></tr></table>"
        )
        return self._row(body)

    # ── spotlight person (photo + name + role + quote) ──────────────────
    def _spotlight_person(self, p: dict[str, Any]) -> str:
        """A person spotlight — employee / volunteer / leader of the month.

        Photo on the left, name + role + quote on the right, in a light card.
        Returns "" when there's nothing meaningful to render.
        """
        name = _esc(p.get("name"))
        role = _esc(p.get("role"))
        quote_html = (p.get("quote_html") or "").strip()
        image_url = (p.get("image_url") or "").strip()
        if not (name or quote_html):
            return ""
        eyebrow = _esc(p.get("eyebrow") or "Spotlight")
        img_cell = (
            f'<td width="34%" valign="top" style="background-color:{_EMERALD_FILL};">'
            + (
                f'<img src="{_esc(image_url)}" width="180" alt="{name}" '
                'style="display:block;width:100%;max-width:180px;height:auto;" />'
                if image_url
                else "&nbsp;"
            )
            + "</td>"
        )
        role_html = (
            f'<p style="margin:2px 0 0;font-size:13px;font-weight:bold;color:{_EMERALD};">{role}</p>' if role else ""
        )
        quote = (
            f'<div style="margin-top:10px;font-size:14px;line-height:1.6;'
            f'font-style:italic;color:{_TEXT};">{quote_html}</div>'
            if quote_html
            else ""
        )
        text_cell = (
            f'<td width="66%" valign="middle" style="padding:20px 22px;">'
            f'<p style="margin:0;font-size:11px;font-weight:bold;letter-spacing:1px;'
            f'text-transform:uppercase;color:{_MUTED};">{eyebrow}</p>'
            f'<p style="margin:6px 0 0;font-size:18px;font-weight:bold;color:#111827;">{name}</p>'
            f"{role_html}{quote}"
            "</td>"
        )
        body = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:16px;overflow:hidden;">'
            f"<tr>{img_cell}{text_cell}</tr></table>"
        )
        return self._row(body)

    # ── volunteer CTA grid ("ways to help") ─────────────────────────────
    def _volunteer_cta_grid(self, p: dict[str, Any]) -> str:
        """A grid of "ways to get involved" cards — title, blurb, optional
        action link. Two columns per row for reliable email rendering. Returns
        "" when there are no items.
        """
        items = [i for i in (p.get("items") or []) if isinstance(i, dict)]
        if not items:
            return ""
        heading = _esc(p.get("heading"))
        intro = _esc(p.get("intro"))
        heading_html = f'<h2 style="margin:0 0 4px;font-size:20px;color:#111827;">{heading}</h2>' if heading else ""
        intro_html = (
            f'<p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:{_MUTED};">{intro}</p>' if intro else ""
        )
        cells = []
        for item in items:
            title = _esc(item.get("title"))
            body = _esc(item.get("body"))
            href = (item.get("href") or "").strip()
            link_html = (
                f'<p style="margin:10px 0 0;"><a href="{_esc(href)}" target="_blank" '
                f'rel="noopener noreferrer" style="font-size:12px;font-weight:bold;'
                f"letter-spacing:0.5px;text-transform:uppercase;color:{_EMERALD};"
                f'text-decoration:none;">{_esc(item.get("label") or "Learn more")} &rarr;</a></p>'
                if href
                else ""
            )
            cells.append(
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:14px;height:100%;">'
                '<tr><td valign="top" style="padding:18px 16px;">'
                f'<p style="margin:0;font-size:15px;font-weight:bold;color:#111827;">{title}</p>'
                + (
                    f'<p style="margin:6px 0 0;font-size:13px;line-height:1.55;color:{_TEXT};">{body}</p>'
                    if body
                    else ""
                )
                + f"{link_html}"
                "</td></tr></table>"
            )
        rows = []
        for i in range(0, len(cells), 2):
            left = cells[i]
            right = cells[i + 1] if i + 1 < len(cells) else ""
            right_td = (
                f'<td width="50%" valign="top" style="padding:0 0 12px 6px;">{right}</td>'
                if right
                else '<td width="50%">&nbsp;</td>'
            )
            rows.append(f'<tr><td width="50%" valign="top" style="padding:0 6px 12px 0;">{left}</td>{right_td}</tr>')
        grid = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            + "".join(rows)
            + "</table>"
        )
        return self._row(f"{heading_html}{intro_html}{grid}")

    # ── events list (upcoming) ──────────────────────────────────────────
    def _events_list(self, p: dict[str, Any]) -> str:
        """A list of upcoming events — each row a date chip + title + location,
        with an optional RSVP/details link. Returns "" when there are no events.
        """
        events = [e for e in (p.get("events") or []) if isinstance(e, dict)]
        if not events:
            return ""
        heading = _esc(p.get("heading") or "Upcoming events")
        rows = []
        for ev in events:
            date = _esc(ev.get("date"))
            title = _esc(ev.get("title"))
            location = _esc(ev.get("location"))
            href = (ev.get("href") or "").strip()
            date_chip = (
                f'<td width="84" valign="top" style="padding:14px 12px 14px 16px;">'
                f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                f'style="background-color:{_EMERALD_FILL};border-radius:10px;"><tr>'
                f'<td align="center" style="padding:8px 10px;font-size:12px;font-weight:bold;'
                f'color:{_EMERALD};">{date}</td></tr></table></td>'
                if date
                else '<td width="16">&nbsp;</td>'
            )
            location_html = (
                f'<p style="margin:3px 0 0;font-size:12px;color:{_MUTED};">{location}</p>' if location else ""
            )
            link_html = (
                f'<p style="margin:6px 0 0;"><a href="{_esc(href)}" target="_blank" '
                f'rel="noopener noreferrer" style="font-size:12px;font-weight:bold;'
                f"letter-spacing:0.5px;text-transform:uppercase;color:{_EMERALD};"
                f'text-decoration:none;">{_esc(ev.get("label") or "Details")} &rarr;</a></p>'
                if href
                else ""
            )
            rows.append(
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:14px;'
                'margin-bottom:10px;"><tr>'
                f"{date_chip}"
                '<td valign="top" style="padding:14px 16px 14px 0;">'
                f'<p style="margin:0;font-size:15px;font-weight:bold;color:#111827;">{title}</p>'
                f"{location_html}{link_html}"
                "</td></tr></table>"
            )
        heading_html = f'<h2 style="margin:0 0 12px;font-size:20px;color:#111827;">{heading}</h2>'
        return self._row(f"{heading_html}{''.join(rows)}")

    # ── icon divider ────────────────────────────────────────────────────
    def _icon_divider(self, p: dict[str, Any]) -> str:
        # Email-safe glyph: a small navy circle with a heart/star char (no
        # icon font). Keeps the "visual breather" beat without web fonts.
        glyph = {"heart": "♥", "sparkle": "✦", "star": "★"}.get(p.get("icon") or "users", "♥")
        caption_html = (p.get("caption_html") or "").strip()
        caption = (
            f'<p style="margin:12px auto 0;max-width:440px;font-size:14px;line-height:1.6;'
            f'color:#334155;">{caption_html}</p>'
            if caption_html
            else ""
        )
        body = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            '<tr><td align="center" style="padding:4px 0;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td align="center" valign="middle" width="44" height="44" '
            f'style="width:44px;height:44px;background-color:{_NAVY};border-radius:22px;'
            f'color:{_AMBER_ON_DARK};font-size:18px;">{glyph}</td>'
            "</tr></table>"
            f"{caption}"
            "</td></tr></table>"
        )
        return self._row(body)

    # ── cta ─────────────────────────────────────────────────────────────
    def _cta(self, p: dict[str, Any]) -> str:
        href = (p.get("href") or "").strip()
        if not href:
            return ""
        label = _esc(p.get("label") or "Support our work")
        tone = p.get("tone") or "dark"
        supporting = _esc(p.get("supporting") or "")
        if tone == "dark":
            btn_bg, btn_color = _NAVY, "#ffffff"
            heading = ""
        else:
            btn_bg, btn_color = _EMERALD, "#ffffff"
            support_html = (
                f'<p style="margin:6px 0 0;font-size:14px;color:{_MUTED};">{supporting}</p>' if supporting else ""
            )
            heading = f'<h3 style="margin:0;font-size:18px;color:#111827;">{label}</h3>{support_html}'
        button = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:14px auto 0;"><tr>'
            f'<td align="center" style="border-radius:999px;background-color:{btn_bg};">'
            f'<a href="{_esc(href)}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-block;padding:13px 30px;font-size:13px;font-weight:bold;'
            f'letter-spacing:1px;text-transform:uppercase;color:{btn_color};text-decoration:none;">'
            f"{label}</a></td></tr></table>"
        )
        wrapper_style = (
            "padding:8px 0;"
            if tone == "dark"
            else f"background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:18px;padding:28px 24px;"
        )
        body = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="{wrapper_style}"><tr><td align="center">{heading}{button}</td></tr></table>'
        )
        return self._row(body)

    # ── footer (dark navy) ──────────────────────────────────────────────
    def _footer(self, p: dict[str, Any]) -> str:
        tagline = _esc(p.get("tagline") or "")
        accent = _esc(p.get("accent_tagline") or "")
        phone = (p.get("phone") or "").strip()
        email = (p.get("email") or "").strip()
        website = (p.get("website") or "").strip()
        copyright_text = _esc(p.get("copyright") or "")

        accent_html = (
            f'<p style="margin:2px 0 0;font-family:{_SERIF};font-style:italic;'
            f'font-size:18px;color:{_AMBER_ON_DARK};">{accent}</p>'
            if accent
            else ""
        )
        contact_lines = []
        if phone:
            contact_lines.append(
                f'<a href="tel:{_esc(phone)}" style="color:{_LIGHT_ON_DARK};text-decoration:none;'
                f'display:block;">{_esc(phone)}</a>'
            )
        if email:
            contact_lines.append(
                f'<a href="mailto:{_esc(email)}" style="color:{_LIGHT_ON_DARK};text-decoration:none;'
                f'display:block;">{_esc(email)}</a>'
            )
        if website:
            display = website.replace("https://", "").replace("http://", "")
            href = website if website.startswith("http") else f"https://{website}"
            contact_lines.append(
                f'<a href="{_esc(href)}" target="_blank" rel="noopener noreferrer" '
                f'style="color:{_LIGHT_ON_DARK};text-decoration:none;display:block;">{_esc(display)}</a>'
            )
        contact_html = (
            f'<div style="font-size:12px;line-height:1.8;color:{_LIGHT_ON_DARK};">' + "".join(contact_lines) + "</div>"
            if contact_lines
            else ""
        )
        # Unsubscribe link uses the dispatch-substituted token so it resolves
        # per recipient (and suppresses the auto-appended defensive footer).
        unsubscribe_html = (
            ""
            if getattr(self, "_document_only", False)
            else (
                f'<p style="margin:10px 0 0;"><a href="{_UNSUBSCRIBE_TOKEN}" '
                f'style="color:{_AMBER_ON_DARK};text-decoration:underline;font-size:12px;">'
                "Unsubscribe</a></p>"
            )
        )
        copyright_html = (
            f'<p style="margin:10px 0 0;font-size:11px;color:{_AMBER_ON_DARK};opacity:0.85;">{copyright_text}</p>'
            if copyright_text
            else ""
        )
        body = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background-color:{_NAVY};border-radius:18px;"><tr>'
            '<td style="padding:28px 26px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td width="55%" valign="top">'
            f'<p style="margin:0;font-size:19px;font-weight:bold;color:#ffffff;">{tagline}</p>'
            f"{accent_html}</td>"
            f'<td width="45%" valign="top">{contact_html}{unsubscribe_html}{copyright_html}</td>'
            "</tr></table>"
            "</td></tr></table>"
        )
        return self._row(body, padding="0")

    # ── legacy fallback card ────────────────────────────────────────────
    def _legacy_card(self, fallback_html: str) -> str:
        inner = (fallback_html or "").strip() or (
            f'<p style="color:{_MUTED};font-size:14px;">This newsletter has no content yet.</p>'
        )
        body = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background-color:{_CARD_BG};border:1px solid {_BORDER};border-radius:18px;">'
            '<tr><td style="padding:28px 26px;">'
            f'<div style="font-size:15px;line-height:1.6;color:{_TEXT};">{inner}</div>'
            "</td></tr></table>"
        )
        return self._row(body)
