"""HTML → PDF adapter for Writing artifacts (drafts + newsletters).

Wraps the shared ``GotenbergHtmlToPdfClient`` and exposes a kind-aware
``render()`` so the same adapter serves both newsletter and writing-draft
PDF exports.

Reuses pattern from
``components/reports/infrastructure/adapters/gotenberg_financial_report_pdf_renderer.py``.
"""

from __future__ import annotations

import logging

from components.shared_platform.infrastructure.services.gotenberg_html_to_pdf_client import (
    GotenbergHtmlToPdfClient,
    GotenbergPageOptions,
    GotenbergRenderError,
)

logger = logging.getLogger(__name__)

# Re-export for callers that want to catch render errors.
WritingPdfRenderError = GotenbergRenderError


def _wrap_body_in_document(*, title: str, body_html: str) -> str:
    """Wrap a raw rich-text body in a minimal printable HTML document.

    Drafts and newsletters store body_html as fragments (what the
    react-quill editor produces). Gotenberg needs a full document. The
    wrapper applies print-friendly base typography; CSS is intentionally
    minimal so authoring decisions in the editor remain visible.
    """

    escaped_title = title.replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{escaped_title}</title>
<style>
@page {{ size: 8.5in 11in; margin: 0.75in; }}
body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #1f2937; line-height: 1.55; font-size: 11pt; }}
h1 {{ font-size: 20pt; margin: 0 0 0.4em; color: #111827; }}
h2 {{ font-size: 14pt; margin: 1.25em 0 0.4em; color: #111827; }}
h3 {{ font-size: 12pt; margin: 1.1em 0 0.3em; }}
p {{ margin: 0 0 0.7em; }}
ul, ol {{ margin: 0 0 0.7em 1.2em; }}
blockquote {{ border-left: 3px solid #d1d5db; padding-left: 0.8em; color: #4b5563; margin: 0.5em 0; }}
img {{ max-width: 100%; height: auto; }}
a {{ color: #2563eb; }}
hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 1.5em 0; }}
</style>
</head>
<body>
<h1>{escaped_title}</h1>
{body_html}
</body>
</html>"""


# Letter-shaped kinds render on the branded letterhead (task #19 — Henry:
# ALL letters ship in the letterhead style by default, never a bare wall of
# text). Other kinds keep the minimal print document.
_LETTERHEAD_KINDS = {"letter"}


def _escape(value: str) -> str:
    return (value or "").replace("<", "&lt;").replace(">", "&gt;")


def _letter_recipient_html(letter_fields: dict) -> str:
    """The addressee block under the brand hairline (task #19)."""
    recipient = letter_fields.get("recipient") if isinstance(letter_fields, dict) else None
    if not isinstance(recipient, dict):
        return ""
    name = _escape(str(recipient.get("name") or ""))
    role = _escape(str(recipient.get("role") or ""))
    org = _escape(str(recipient.get("org") or ""))
    if not (name or role or org):
        return ""
    lines = []
    if name:
        lines.append(f'<p style="margin:0;font-weight:600;">{name}</p>')
    for extra in (role, org):
        if extra:
            lines.append(f'<p style="margin:0;color:#4b5563;">{extra}</p>')
    return f'<div style="margin:0 0 0.3in;font-size:10pt;line-height:1.45;">{"".join(lines)}</div>'


def _letter_signature_html(letter_fields: dict) -> str:
    """The script-signed closing after the body (task #19). The script stack
    mirrors the frontend LetterheadFrame so editor/drawer/PDF agree."""
    signature = letter_fields.get("signature") if isinstance(letter_fields, dict) else None
    if not isinstance(signature, dict):
        return ""
    name = _escape(str(signature.get("name") or ""))
    image_url = str(signature.get("image_url") or "").strip()
    if not (name or image_url):
        return ""
    role = _escape(str(signature.get("role") or ""))
    role_line = f'<p style="margin:2px 0 0;font-size:9pt;color:#4b5563;">{role}</p>' if role else ""
    # A real signature image (from the brand library) beats the script-font
    # rendering of the name; the typed name always prints beneath either.
    if image_url:
        sign_line = f'<img src="{_escape(image_url)}" alt="" style="display:block;max-height:0.7in;max-width:2.6in;" />'
    else:
        sign_line = (
            f"<p style=\"margin:0;font-family:'Snell Roundhand','Segoe Script','Brush Script MT',cursive;"
            f'font-size:20pt;color:#111827;">{name}</p>'
        )
    name_line = f'<p style="margin:4px 0 0;font-size:10pt;font-weight:600;color:#1f2937;">{name}</p>' if name else ""
    return f'<div style="margin-top:0.4in;">{sign_line}{name_line}{role_line}</div>'


def _wrap_letter_in_letterhead(
    *,
    title: str,
    body_html: str,
    org_name: str,
    contact_email: str,
    letter_date: str,
    brand: dict[str, str],
    letter_fields: dict | None = None,
) -> str:
    """Wrap a letter body in the branded letterhead document.

    Anatomy (from the approved Canva letterhead reference): a full-width
    brand band top and a thin one at the foot, the organisation's name in
    wide-tracked caps with its contact line, the date right-aligned above a
    brand hairline, then the justified letter body. Colours and font stacks
    come from the workspace brand (``resolve_brand_colors`` — failure-safe,
    Octopus fallback), so every org's letters come out in their own colours.
    """

    escaped_title = title.replace("<", "&lt;").replace(">", "&gt;")
    escaped_org = (org_name or "").replace("<", "&lt;").replace(">", "&gt;")
    escaped_email = (contact_email or "").replace("<", "&lt;").replace(">", "&gt;")
    primary = brand.get("primary_light") or "#10b981"
    heading_stack = brand.get("font_heading_stack") or "Georgia, 'Times New Roman', serif"
    body_stack = brand.get("font_body_stack") or "'Helvetica Neue', Arial, sans-serif"

    contact_line = (
        f'<p style="margin:2px 0 0;font-size:9pt;color:#6b7280;">{escaped_email}</p>' if escaped_email else ""
    )
    date_line = (
        f'<p style="margin:0;font-size:10pt;color:#374151;text-align:right;">{letter_date}</p>' if letter_date else ""
    )
    recipient_block = _letter_recipient_html(letter_fields or {})
    signature_block = _letter_signature_html(letter_fields or {})

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{escaped_title}</title>
<style>
@page {{ size: 8.5in 11in; margin: 0; }}
body {{ margin: 0; font-family: {body_stack}; color: #1f2937; line-height: 1.7; font-size: 11pt; }}
.band {{ height: 0.35in; background: {primary}; }}
.band-foot {{ height: 0.14in; background: {primary}; }}
.page {{ padding: 0.45in 0.9in 0.6in; min-height: 9.2in; display: flex; flex-direction: column; }}
.org {{ font-family: {heading_stack}; font-size: 17pt; letter-spacing: 0.18em; text-transform: uppercase; color: #111827; margin: 0; }}
.rule {{ border: none; border-top: 2px solid {primary}; margin: 0.18in 0 0.35in; }}
.body {{ text-align: justify; flex: 1; }}
.body p {{ margin: 0 0 0.85em; }}
.body h2 {{ font-family: {heading_stack}; font-size: 13pt; margin: 1.2em 0 0.4em; color: #111827; }}
.body blockquote {{ border-left: 3px solid {primary}; padding-left: 0.8em; color: #4b5563; margin: 0.5em 0; }}
.body img {{ max-width: 100%; height: auto; }}
.body a {{ color: {primary}; }}
</style>
</head>
<body>
<div class="band"></div>
<div class="page">
  <div style="display:flex;justify-content:space-between;align-items:flex-end;">
    <div>
      <p class="org">{escaped_org or escaped_title}</p>
      {contact_line}
    </div>
    <div>{date_line}</div>
  </div>
  <hr class="rule" />
  {recipient_block}
  <div class="body">{body_html}</div>
  {signature_block}
</div>
<div class="band-foot"></div>
</body>
</html>"""


def _load_letterhead_org_fields(workspace_id: str) -> tuple[str, str]:
    """Best-effort (org_name, contact_email) — a lookup failure renders a
    letter without the sender block rather than failing the export."""
    try:
        from infrastructure.persistence.workspaces.models import Workspace

        workspace = Workspace.objects.filter(pk=workspace_id).only("workspace_name", "contact_email").first()
        if workspace is not None:
            return workspace.workspace_name or "", workspace.contact_email or ""
    except Exception:
        logger.exception("writing_pdf.letterhead_org_lookup_failed workspace=%s", workspace_id)
    return "", ""


class GotenbergWritingPdfAdapter:
    """Renders Newsletter and WritingDraft HTML to PDF bytes."""

    PAGE_OPTIONS = GotenbergPageOptions(
        margin_top="0.75in",
        margin_bottom="0.75in",
        margin_left="0.75in",
        margin_right="0.75in",
    )

    # Letterhead pages own their margins (full-bleed brand bands).
    LETTERHEAD_PAGE_OPTIONS = GotenbergPageOptions(
        margin_top="0in",
        margin_bottom="0in",
        margin_left="0in",
        margin_right="0in",
    )

    def __init__(self, client: GotenbergHtmlToPdfClient | None = None) -> None:
        self._client = client or GotenbergHtmlToPdfClient()

    def render(
        self,
        *,
        kind: str,
        artifact_id: str,
        workspace_id: str,
        title: str,
        body_html: str,
        document_html: str | None = None,
        letter_date: str = "",
        letter_fields: dict | None = None,
    ) -> bytes:
        # ``document_html`` is a complete, self-contained HTML document (e.g.
        # the newsletter block tree already rendered to email-safe HTML) — send
        # it to Gotenberg as-is so the PDF matches the sent email exactly. When
        # absent (writing drafts, legacy callers) wrap the raw ``body_html``
        # fragment in the minimal print document — or, for letter-shaped
        # kinds, in the branded letterhead (task #19).
        page_options = self.PAGE_OPTIONS
        if document_html:
            html = document_html
        elif kind in _LETTERHEAD_KINDS:
            from components.shared_platform.infrastructure.services.pdf_brand_assets import (
                resolve_brand_colors,
            )

            org_name, contact_email = _load_letterhead_org_fields(workspace_id)
            html = _wrap_letter_in_letterhead(
                title=title,
                body_html=body_html,
                org_name=org_name,
                contact_email=contact_email,
                letter_date=letter_date,
                brand=resolve_brand_colors(workspace_id),
                letter_fields=letter_fields,
            )
            page_options = self.LETTERHEAD_PAGE_OPTIONS
        else:
            html = _wrap_body_in_document(title=title, body_html=body_html)
        return self._client.render(
            html=html,
            page_options=page_options,
            log_context={
                "kind": kind,
                "artifact_id": artifact_id,
                "workspace": workspace_id,
            },
        )
