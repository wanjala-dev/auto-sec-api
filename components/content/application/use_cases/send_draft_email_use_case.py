"""Email a writing draft to a small, explicit set of contacts (task #20).

The distribution leg of the content wedge: generate → approve → SEND.
This is 1:few correspondence (a report to three funders, an update to a
board member) — deliberately NOT the bulk path. Bulk goes through the
newsletter surface (subscribers + segments + unsubscribe compliance);
this use case caps recipients and sends through the shared
EmailSendingPort like every other transactional mail.

Rendering rides the same seam as send/PDF/preview: a designed draft's
block layout renders through NewsletterHtmlRenderPort (document mode —
no unsubscribe chrome); prose drafts get a minimal document wrap.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from components.content.application.ports.contact_email_lookup_port import (
    ContactEmailLookupPort,
)
from components.content.application.ports.newsletter_html_render_port import (
    NewsletterHtmlRenderPort,
)
from components.content.domain.errors import ContentValidationError
from components.shared_platform.application.ports.email_sending_port import (
    EmailMessage,
    EmailSendingPort,
)

logger = logging.getLogger(__name__)

# Correspondence, not broadcast — bulk sending belongs to the newsletter
# surface with its unsubscribe compliance. The cap keeps this path honest.
MAX_RECIPIENTS = 20


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value or "").strip()


@dataclass
class SendDraftEmailUseCase:
    drafts: Any  # WritingDraftRepository (get)
    contact_emails: ContactEmailLookupPort
    html_render: NewsletterHtmlRenderPort
    email: EmailSendingPort

    def execute(
        self,
        *,
        draft_id: UUID,
        contact_ids: Sequence[UUID],
        note: str = "",
    ) -> dict:
        if not contact_ids:
            raise ContentValidationError("Pick at least one contact to send to.")
        if len(contact_ids) > MAX_RECIPIENTS:
            raise ContentValidationError(
                f"Send to at most {MAX_RECIPIENTS} contacts at a time — for "
                "larger audiences use a newsletter to a segment."
            )

        draft = self.drafts.get(draft_id=draft_id)
        if draft is None:
            raise ContentValidationError("Draft not found.")
        # The draft row is the workspace authority — recipients resolve
        # against ITS workspace, never a client-supplied id.
        workspace_id = draft.workspace_id

        recipients = self.contact_emails.lookup(workspace_id=workspace_id, contact_ids=list(contact_ids))
        if not recipients:
            raise ContentValidationError("None of the selected contacts has an email address.")

        subject = (draft.title or "").strip() or "A document for you"
        body_html = self._render_body(draft)
        note_html = (
            f'<p style="margin:0 0 16px;color:#374151;">{html_lib.escape(note.strip())}</p>'
            if (note or "").strip()
            else ""
        )

        sent, failed = 0, 0
        for recipient in recipients:
            ok = False
            try:
                ok = self.email.send(
                    EmailMessage(
                        subject=subject,
                        to=[recipient["email"]],
                        html_body=f"{note_html}{body_html}",
                        text_body=(f"{(note or '').strip()}\n\n{_strip_tags(draft.body_html)}").strip(),
                    )
                )
            except Exception:
                logger.exception(
                    "draft_email.send_failed draft_id=%s workspace_id=%s contact_id=%s",
                    draft_id,
                    workspace_id,
                    recipient.get("id"),
                )
            if ok:
                sent += 1
            else:
                failed += 1

        logger.info(
            "draft_email.sent draft_id=%s workspace_id=%s sent=%s failed=%s skipped=%s",
            draft_id,
            workspace_id,
            sent,
            failed,
            len(contact_ids) - len(recipients),
        )
        return {
            "sent": sent,
            "failed": failed,
            "skipped_without_email": len(contact_ids) - len(recipients),
            "recipients": [r["email"] for r in recipients],
        }

    def _render_body(self, draft: Any) -> str:
        layout = (getattr(draft, "metadata", None) or {}).get("layout")
        if isinstance(layout, dict) and layout.get("blocks"):
            # Same renderer as send/PDF/preview; a draft emailed to a person
            # is a document, not a marketing email — no unsubscribe chrome.
            return self.html_render.render(
                layout=layout,
                fallback_html=draft.body_html,
                context={"document_only": True},
            )
        title = html_lib.escape((draft.title or "").strip())
        heading = f'<h2 style="margin:0 0 12px;color:#111827;">{title}</h2>' if title else ""
        return (
            "<div style=\"font-family:Arial,'Helvetica Neue',sans-serif;"
            'color:#1f2937;line-height:1.7;max-width:640px;">'
            f"{heading}{draft.body_html or ''}"
            "</div>"
        )
