"""Provider: wires writing use cases against their adapters.

Factory pattern. Other layers (API controllers, Celery workers) ask the
provider for a ready-to-use ``use_case`` instance and stay agnostic of
the concrete adapter wiring.
"""

from __future__ import annotations

from components.content.application.use_cases.confirm_subscription_use_case import (
    ConfirmSubscriptionUseCase,
)
from components.content.application.use_cases.count_eligible_recipients_use_case import (
    CountEligibleRecipientsUseCase,
)
from components.content.application.use_cases.create_writing_draft_use_case import (
    CreateWritingDraftUseCase,
)
from components.content.application.use_cases.dispatch_due_scheduled_newsletters_use_case import (
    DispatchDueScheduledNewslettersUseCase,
)
from components.content.application.use_cases.dispatch_scheduled_newsletters_use_case import (
    DispatchScheduledNewslettersUseCase,
)
from components.content.application.use_cases.enroll_directory_contacts_use_case import (
    EnrollDirectoryContactsUseCase,
)
from components.content.application.use_cases.generate_newsletter_use_case import (
    GenerateNewsletterUseCase,
)
from components.content.application.use_cases.list_writing_artifacts_use_case import (
    ListWritingArtifactsUseCase,
)
from components.content.application.use_cases.publish_writing_draft_use_case import (
    PublishWritingDraftUseCase,
)
from components.content.application.use_cases.record_email_bounce_use_case import (
    RecordEmailBounceUseCase,
)
from components.content.application.use_cases.record_email_complaint_use_case import (
    RecordEmailComplaintUseCase,
)
from components.content.application.use_cases.resolve_default_design_layout_use_case import (
    ResolveDefaultDesignLayoutUseCase,
)
from components.content.application.use_cases.send_draft_email_use_case import (
    SendDraftEmailUseCase,
)
from components.content.application.use_cases.send_newsletter_use_case import (
    SendNewsletterUseCase,
)
from components.content.application.use_cases.send_test_newsletter_use_case import (
    SendTestNewsletterUseCase,
)
from components.content.application.use_cases.subscribe_publicly_use_case import (
    SubscribePubliclyUseCase,
)
from components.content.application.use_cases.unsubscribe_subscriber_use_case import (
    UnsubscribeSubscriberUseCase,
)


class WritingProvider:
    """Build use case instances with all adapters wired."""

    # ── Drafts ─────────────────────────────────────────────────────────

    def build_create_writing_draft(self) -> CreateWritingDraftUseCase:
        from components.content.infrastructure.adapters.template_placeholder_resolver import (
            TemplatePlaceholderResolver,
        )
        from components.content.infrastructure.repositories.writing_draft_repository import (
            WritingDraftRepository,
        )
        from components.content.infrastructure.repositories.writing_template_repository import (
            WritingTemplateRepository,
        )

        return CreateWritingDraftUseCase(
            writing_drafts=WritingDraftRepository(),
            writing_templates=WritingTemplateRepository(),
            placeholder_resolver=TemplatePlaceholderResolver(),
        )

    def build_send_draft_email(self) -> SendDraftEmailUseCase:
        from components.content.infrastructure.adapters.contact_email_lookup_adapter import (
            ContactEmailLookupAdapter,
        )
        from components.content.infrastructure.adapters.email_newsletter_html_render_adapter import (
            EmailNewsletterHtmlRenderAdapter,
        )
        from components.content.infrastructure.repositories.writing_draft_repository import (
            WritingDraftRepository,
        )
        from components.shared_platform.application.providers.email_adapter_provider import (
            get_email_adapter_provider,
        )

        return SendDraftEmailUseCase(
            drafts=WritingDraftRepository(),
            contact_emails=ContactEmailLookupAdapter(),
            html_render=EmailNewsletterHtmlRenderAdapter(),
            email=get_email_adapter_provider().adapter(),
        )

    def build_resolve_default_design_layout(self) -> ResolveDefaultDesignLayoutUseCase:
        from components.content.infrastructure.adapters.template_placeholder_resolver import (
            TemplatePlaceholderResolver,
        )
        from components.content.infrastructure.repositories.writing_template_repository import (
            WritingTemplateRepository,
        )

        return ResolveDefaultDesignLayoutUseCase(
            writing_templates=WritingTemplateRepository(),
            placeholder_resolver=TemplatePlaceholderResolver(),
        )

    def build_publish_writing_draft(self) -> PublishWritingDraftUseCase:
        from components.content.infrastructure.repositories.writing_draft_repository import (
            WritingDraftRepository,
        )
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        repo = WritingDraftRepository()
        return PublishWritingDraftUseCase(
            writing_draft_store=repo,
            writing_draft_reader=repo,
            event_publisher=CeleryEventPublisher(),
        )

    # ── Newsletters ────────────────────────────────────────────────────

    def build_generate_newsletter(self) -> GenerateNewsletterUseCase:
        from components.content.infrastructure.adapters.langchain_newsletter_ai_adapter import (
            LangchainNewsletterAiAdapter,
        )
        from components.content.infrastructure.adapters.workspace_brand_voice_adapter import (
            WorkspaceBrandVoiceAdapter,
        )
        from components.content.infrastructure.repositories.newsletter_read_repository import (
            NewsletterReadRepository,
        )
        from components.content.infrastructure.repositories.newsletter_store_repository import (
            NewsletterStoreRepository,
        )
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        return GenerateNewsletterUseCase(
            newsletter_store=NewsletterStoreRepository(),
            newsletter_reader=NewsletterReadRepository(),
            newsletter_ai=LangchainNewsletterAiAdapter(),
            event_publisher=CeleryEventPublisher(),
            brand_voice=WorkspaceBrandVoiceAdapter(),
        )

    def build_send_newsletter(self) -> SendNewsletterUseCase:
        from components.content.infrastructure.adapters.email_newsletter_dispatch_adapter import (
            EmailNewsletterDispatchAdapter,
        )
        from components.content.infrastructure.adapters.email_newsletter_html_render_adapter import (
            EmailNewsletterHtmlRenderAdapter,
        )
        from components.content.infrastructure.adapters.faithfulness_check_adapter import (
            AgentsFaithfulnessCheckAdapter,
        )
        from components.content.infrastructure.adapters.newsletter_dispatch_ledger_adapter import (
            NewsletterDispatchLedgerAdapter,
        )
        from components.content.infrastructure.repositories.newsletter_read_repository import (
            NewsletterReadRepository,
        )
        from components.content.infrastructure.repositories.newsletter_store_repository import (
            NewsletterStoreRepository,
        )
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        return SendNewsletterUseCase(
            newsletter_store=NewsletterStoreRepository(),
            newsletter_reader=NewsletterReadRepository(),
            newsletter_dispatch=EmailNewsletterDispatchAdapter(),
            newsletter_html_render=EmailNewsletterHtmlRenderAdapter(),
            event_publisher=CeleryEventPublisher(),
            faithfulness_check=AgentsFaithfulnessCheckAdapter(),
            dispatch_ledger=NewsletterDispatchLedgerAdapter(),
        )

    def build_record_ai_provenance(self):
        """Persist trimmed ask-ai provenance onto the artifact's metadata
        (task #22) so the Details drawer can show cited sources durably."""
        from components.content.application.use_cases.record_ai_provenance_use_case import (
            RecordAiProvenanceUseCase,
        )
        from components.content.infrastructure.repositories.newsletter_store_repository import (
            NewsletterStoreRepository,
        )
        from components.content.infrastructure.repositories.writing_draft_repository import (
            WritingDraftRepository,
        )

        return RecordAiProvenanceUseCase(
            draft_store=WritingDraftRepository(),
            newsletter_store=NewsletterStoreRepository(),
        )

    def build_dispatch_ledger(self):
        """The per-recipient send ledger (task #25) — also the open-pixel
        endpoint's write path."""
        from components.content.infrastructure.adapters.newsletter_dispatch_ledger_adapter import (
            NewsletterDispatchLedgerAdapter,
        )

        return NewsletterDispatchLedgerAdapter()

    def build_count_eligible_recipients(self) -> CountEligibleRecipientsUseCase:
        """Cross-context surface: contacts' segment-send preview asks how many
        of a set of addresses are send-eligible subscribers in this workspace."""
        from components.content.infrastructure.repositories.newsletter_read_repository import (
            NewsletterReadRepository,
        )

        return CountEligibleRecipientsUseCase(
            newsletter_reader=NewsletterReadRepository(),
        )

    def build_enroll_directory_contacts(self) -> EnrollDirectoryContactsUseCase:
        """Cross-context surface: contacts' deliberate "add segment to my
        newsletter list" action enrolls each directory contact as a subscriber
        (create-only — never resurrects an opt-out)."""
        from components.content.infrastructure.repositories.subscriber_repository import (
            SubscriberRepository,
        )

        return EnrollDirectoryContactsUseCase(
            subscriber_store=SubscriberRepository(),
        )

    def build_dispatch_scheduled_newsletters(
        self,
    ) -> DispatchScheduledNewslettersUseCase:
        from components.content.infrastructure.adapters.newsletter_metrics_collector_adapter import (
            NewsletterMetricsCollectorAdapter,
        )
        from components.content.infrastructure.adapters.workspace_cadence_query_adapter import (
            WorkspaceCadenceQueryAdapter,
        )

        return DispatchScheduledNewslettersUseCase(
            cadence_queries=WorkspaceCadenceQueryAdapter(),
            metrics_collector=NewsletterMetricsCollectorAdapter(),
            generate_newsletter=self.build_generate_newsletter(),
        )

    # ── Unified artifacts ──────────────────────────────────────────────

    def build_list_writing_artifacts(self) -> ListWritingArtifactsUseCase:
        from components.content.infrastructure.repositories.writing_artifacts_repository import (
            WritingArtifactsRepository,
        )

        return ListWritingArtifactsUseCase(
            writing_artifacts=WritingArtifactsRepository(),
        )

    # ── Subscribe + suppression compliance loop ────────────────────────

    def build_subscribe_publicly(self) -> SubscribePubliclyUseCase:
        from components.content.infrastructure.repositories.subscriber_repository import (
            SubscriberRepository,
        )

        return SubscribePubliclyUseCase(
            subscriber_store=SubscriberRepository(),
        )

    def build_confirm_subscription(self) -> ConfirmSubscriptionUseCase:
        from components.content.infrastructure.repositories.subscriber_repository import (
            SubscriberRepository,
        )

        return ConfirmSubscriptionUseCase(
            subscriber_store=SubscriberRepository(),
        )

    def build_unsubscribe_subscriber(self) -> UnsubscribeSubscriberUseCase:
        from components.content.infrastructure.repositories.subscriber_repository import (
            SubscriberRepository,
        )

        return UnsubscribeSubscriberUseCase(
            subscriber_store=SubscriberRepository(),
        )

    def build_record_email_bounce(self) -> RecordEmailBounceUseCase:
        from components.content.infrastructure.repositories.subscriber_repository import (
            SubscriberRepository,
        )
        from components.content.infrastructure.repositories.suppression_repository import (
            SuppressionRepository,
        )

        return RecordEmailBounceUseCase(
            subscriber_store=SubscriberRepository(),
            suppression_store=SuppressionRepository(),
        )

    def build_record_email_complaint(self) -> RecordEmailComplaintUseCase:
        from components.content.infrastructure.repositories.subscriber_repository import (
            SubscriberRepository,
        )
        from components.content.infrastructure.repositories.suppression_repository import (
            SuppressionRepository,
        )

        return RecordEmailComplaintUseCase(
            subscriber_store=SubscriberRepository(),
            suppression_store=SuppressionRepository(),
        )

    # ── Test-send + scheduled-send ─────────────────────────────────────

    def build_send_test_newsletter(self) -> SendTestNewsletterUseCase:
        from components.content.infrastructure.adapters.email_newsletter_dispatch_adapter import (
            EmailNewsletterDispatchAdapter,
        )
        from components.content.infrastructure.adapters.email_newsletter_html_render_adapter import (
            EmailNewsletterHtmlRenderAdapter,
        )
        from components.content.infrastructure.adapters.faithfulness_check_adapter import (
            AgentsFaithfulnessCheckAdapter,
        )
        from components.content.infrastructure.repositories.newsletter_read_repository import (
            NewsletterReadRepository,
        )

        return SendTestNewsletterUseCase(
            newsletter_reader=NewsletterReadRepository(),
            newsletter_dispatch=EmailNewsletterDispatchAdapter(),
            newsletter_html_render=EmailNewsletterHtmlRenderAdapter(),
            faithfulness_check=AgentsFaithfulnessCheckAdapter(),
        )

    def build_dispatch_due_scheduled_newsletters(
        self,
    ) -> DispatchDueScheduledNewslettersUseCase:
        from components.content.infrastructure.repositories.newsletter_read_repository import (
            NewsletterReadRepository,
        )
        from components.content.infrastructure.repositories.newsletter_store_repository import (
            NewsletterStoreRepository,
        )

        return DispatchDueScheduledNewslettersUseCase(
            newsletter_reader=NewsletterReadRepository(),
            newsletter_store=NewsletterStoreRepository(),
            send_newsletter=self.build_send_newsletter(),
        )
