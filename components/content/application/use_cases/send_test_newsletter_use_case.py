"""Use case: send a test newsletter only to the calling user.

Used by the editor's "Send test to me" button on the pre-send confirm
modal. Reuses the per-recipient dispatch adapter so the test message is
byte-identical to what subscribers will get — including the tokenized
unsubscribe footer + List-Unsubscribe header — except for:

- Subject is prefixed ``[TEST]`` so the recipient can sort it out.
- The synthetic ``SubscriberDispatchTarget`` uses a freshly generated
  token tagged as test in the source_event so SES bounce/complaint
  handlers can recognise + skip it (Phase 2 work; Phase 1 just generates
  a unique throwaway token).
- Does NOT call mark_sent — the newsletter row stays in its current
  status (DRAFT / SCHEDULED / etc.). Test send is purely diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from components.shared_kernel.application.ports.settings_port import (
    SettingsPort,
)


def _settings() -> SettingsPort:
    """Return the default Django-backed settings adapter.

    Lazy import keeps the application layer's import graph clean.
    Override in tests by monkeypatching this function.
    """
    from components.shared_kernel.infrastructure.adapters.django_settings_adapter import (
        DjangoSettingsAdapter,
    )
    return DjangoSettingsAdapter()


from components.content.application.ports.faithfulness_check_port import (
    FaithfulnessCheckPort,
)
from components.content.application.ports.newsletter_dispatch_port import (
    NewsletterDispatchPort,
)
from components.content.application.ports.newsletter_html_render_port import (
    NewsletterHtmlRenderPort,
)
from components.content.application.ports.newsletter_reader_port import (
    NewsletterReaderPort,
)
from components.content.application.use_cases.faithfulness_gate import (
    enforce_faithfulness_gate,
)
from components.content.domain.errors import NewsletterNotFoundError
from components.content.domain.value_objects.subscriber_dispatch_target import (
    SubscriberDispatchTarget,
)


@dataclass
class SendTestNewsletterUseCase:
    newsletter_reader: NewsletterReaderPort
    newsletter_dispatch: NewsletterDispatchPort
    newsletter_html_render: NewsletterHtmlRenderPort
    # Optional so existing constructions keep working; the provider wires
    # the real checker. When unset, the faithfulness gate is a no-op.
    faithfulness_check: FaithfulnessCheckPort | None = None

    def execute(
        self,
        *,
        newsletter_id: UUID,
        recipient_email: str,
        recipient_name: str = "",
        override_unverified: bool = False,
    ) -> None:
        current = self.newsletter_reader.get(newsletter_id=newsletter_id)
        if current is None:
            raise NewsletterNotFoundError(str(newsletter_id))

        subject = "[TEST] " + (current.subject or current.title).strip()
        sender_name = (current.from_name or "").strip() or None
        reply_to = (current.reply_to or "").strip() or None

        # Synthetic target — throwaway token, just enough for the
        # dispatch adapter's per-recipient pipeline to work end-to-end
        # (substitution + header + footer) without touching the real
        # Subscriber table.
        test_target = SubscriberDispatchTarget(
            email=recipient_email,
            unsubscribe_token=uuid4(),
            name=recipient_name,
        )

        settings = _settings()
        frontend_url = settings.get("FRONTEND_URL", "").rstrip("/")
        list_unsubscribe_base_url = f"{frontend_url}/u/" if frontend_url else "/u/"
        list_unsubscribe_mailto = settings.get(
            "EMAIL_UNSUBSCRIBE_MAILTO", "unsubscribe@octopusintl.org"
        )

        # Render the block tree to email-safe HTML so the test message is
        # byte-identical to the real send (same renderer feeds both).
        html_body = self.newsletter_html_render.render(
            layout=(current.content_payload or {}).get("layout"),
            fallback_html=current.content_html,
            context={"preheader": current.preheader},
        )

        # Same faithfulness gate as the real send so the operator is warned
        # about ungrounded figures on the test before dispatching for real.
        enforce_faithfulness_gate(
            faithfulness_check=self.faithfulness_check,
            newsletter=current,
            html_body=html_body,
            override_unverified=override_unverified,
        )

        self.newsletter_dispatch.send(
            subject=subject,
            html_body=html_body,
            plain_body="",  # adapter computes plain from HTML
            targets=[test_target],
            sender_name=sender_name,
            reply_to=reply_to,
            list_unsubscribe_base_url=list_unsubscribe_base_url,
            list_unsubscribe_mailto=list_unsubscribe_mailto,
        )
