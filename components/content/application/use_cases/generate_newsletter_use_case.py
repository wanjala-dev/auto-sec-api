"""Use case: produce a newsletter draft (via the writing_agent AI port).

Called by the Celery cadence task ``content.generate_newsletter_draft`` and
also reachable from the API for "Draft now" manual triggers.

CRITICAL: This use case ALWAYS creates the row at ``status=AI_DRAFTED``.
It never flips to ``SENT``. Sending is gated by ``SendNewsletterUseCase``
which requires explicit human action.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from components.content.application.ports.brand_voice_port import (
    BrandVoicePort,
)
from components.content.application.ports.newsletter_ai_port import (
    NewsletterAiPort,
)
from components.content.application.ports.newsletter_reader_port import (
    NewsletterReaderPort,
)
from components.content.application.ports.newsletter_store_port import (
    NewsletterStorePort,
)
from components.content.domain.entities.newsletter_entity import NewsletterEntity
from components.content.domain.enums import NewsletterStatus
from components.content.domain.events.newsletter_drafted_event import (
    NewsletterDrafted,
)
from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
    CeleryEventPublisher,
)


# Curated, warm, nonprofit/community/education stock photos (Unsplash CDN —
# hotlinkable). Used as the hero image ONLY when a workspace hasn't set its own
# cover/logo, so a newsletter is never a bare text hero. Direct ``images.
# unsplash.com`` URLs are stable; ``?w=1200&q=70`` keeps the email payload light.
_FALLBACK_HERO_IMAGES = (
    "https://images.unsplash.com/photo-1488521787991-ed7bbaae773c?w=1200&q=70",
    "https://images.unsplash.com/photo-1497486751825-1233686d5d80?w=1200&q=70",
    "https://images.unsplash.com/photo-1511949860663-92c5c57d48a7?w=1200&q=70",
    "https://images.unsplash.com/photo-1542810634-71277d95dcbb?w=1200&q=70",
    "https://images.unsplash.com/photo-1469571486292-0ba58a3f068b?w=1200&q=70",
)


def _fallback_hero_image(workspace_id: UUID) -> str:
    """Pick a stable curated hero photo for a workspace with no image of its own.

    Deterministic by workspace id so the same org always gets the same photo
    (consistent brand feel across issues) while different orgs vary.
    """
    index = int(workspace_id.int % len(_FALLBACK_HERO_IMAGES))
    return _FALLBACK_HERO_IMAGES[index]


def _fallback_thanks_image(workspace_id: UUID) -> str:
    """A curated photo for the 'A Word of Thanks' card, offset from the hero so
    a workspace with no images of its own doesn't show the same photo twice."""
    index = int((workspace_id.int + 1) % len(_FALLBACK_HERO_IMAGES))
    return _FALLBACK_HERO_IMAGES[index]


# Section headings the deterministic fallback summary emits. We card-ify a couple
# and drop the prose that merely restates the KPI cards, so a newsletter reads as
# punchy cards (the St. Brigid's reference) instead of a wall of text.
_THANKS_HEADINGS = ("thank you", "thanks", "a word of thanks")
_CTA_HEADINGS = ("get involved", "support our work", "support us", "donate")
_KPI_REDUNDANT_HEADINGS = ("giving highlights", "people we serve")


def _cardify_sections(
    sections: list[dict[str, Any]],
    *,
    thanks_image_url: str,
    drop_kpi_prose: bool,
    cta_available: bool,
) -> tuple[list[dict[str, Any]], str]:
    """Turn flat text sections into a card-driven mix.

    - The 'Thank you' section becomes a two-column image card ('A Word of
      *Thanks*') by attaching a spotlight image + serif accent word.
    - The 'Get involved' section is removed *only when a CTA pill will render*
      (``cta_available``) — its copy is returned as the pill's supporting text.
      Without a pill we keep the prose so the call-to-action isn't lost.
    - When the KPI cards will render the numbers, the 'Giving highlights' /
      'People we serve' prose is dropped so figures aren't repeated.

    Returns ``(sections, cta_supporting)``. Pure — no I/O.
    """
    result: list[dict[str, Any]] = []
    cta_supporting = ""
    for section in sections:
        heading = (section.get("heading") or "").strip()
        key = heading.lower()
        if key in _CTA_HEADINGS:
            import re as _re

            text = _re.sub(r"<[^>]+>", "", section.get("html") or "").strip()
            if cta_available:
                # The pill replaces the prose; keep its copy as supporting text.
                if not cta_supporting:
                    cta_supporting = text
                continue
            result.append(section)  # no pill — keep the prose
            continue
        if drop_kpi_prose and key in _KPI_REDUNDANT_HEADINGS:
            continue
        if key in _THANKS_HEADINGS and thanks_image_url:
            result.append(
                {
                    **section,
                    "heading": "A Word of",
                    "accent_word": "Thanks",
                    "spotlight_image_url": thanks_image_url,
                    "spotlight_layout": "image_left",
                }
            )
            continue
        result.append(section)
    return result, cta_supporting


def _kpi_metrics_present(metrics: dict[str, Any]) -> bool:
    """Whether the composer's KPI cards block will render (mirrors its keys)."""
    return any(
        metrics.get(k)
        for k in (
            "donations_total",
            "donations_amount_total",
            "donations_count",
            "new_supporters",
            "new_recipients",
            "recipient_count",
            "recipients_total",
            "upcoming_events_count",
        )
    )


def _workspace_donate_url(workspace_id: UUID) -> str:
    """Public donate link for the workspace, or '' if no frontend base is set.

    Reads the frontend base via the SettingsPort adapter (same pattern as the
    send use case) rather than importing ``django.conf`` directly — the
    application layer must stay framework-free.
    """
    try:
        from components.shared_kernel.infrastructure.adapters.django_settings_adapter import (
            DjangoSettingsAdapter,
        )

        base = (DjangoSettingsAdapter().get("FRONTEND_URL", "") or "").rstrip("/")
        if base:
            return f"{base}/donate/workspace/{workspace_id}"
    except Exception:  # noqa: BLE001
        pass
    return ""


@dataclass
class GenerateNewsletterUseCase:
    newsletter_store: NewsletterStorePort
    newsletter_reader: NewsletterReaderPort
    newsletter_ai: NewsletterAiPort
    event_publisher: CeleryEventPublisher
    # Canonical brand voice (tone + guidelines) from the workspace brand kit.
    # Optional so legacy constructions keep working; the adapter is
    # failure-safe, so a blank/missing voice simply means no steering.
    brand_voice: BrandVoicePort | None = None

    def execute(
        self,
        *,
        workspace_id: UUID,
        period_start: datetime.date,
        period_end: datetime.date,
        metrics: dict[str, Any],
        user_guidance: str = "",
        force: bool = False,
    ) -> NewsletterEntity:
        # Idempotency — if a newsletter for this period already exists,
        # return it instead of producing a duplicate draft. Mirrors the
        # idempotency key on SendScheduledFinancialReportUseCase.
        #
        # ``force=True`` bypasses the early-return and overwrites the
        # existing draft in place (same UUID, refreshed content). Used
        # by the editor's "Regenerate" action so the operator can pull
        # a new AI draft after editing workspace data without creating
        # a duplicate newsletter row. The store refuses to overwrite a
        # SENT newsletter (audit trail is preserved).
        existing = self.newsletter_reader.find_for_period(
            workspace_id=workspace_id,
            period_start=period_start,
            period_end=period_end,
        )
        if existing is not None and not force:
            return existing

        # Resolve workspace fields up-front — needed both for the grounded
        # deterministic fallback (org name in the prose) and for the hero
        # + footer layout blocks below.
        (
            workspace_name,
            workspace_contact_email,
            workspace_mission,
            workspace_cover_photo_url,
            workspace_photo_url,
        ) = self._load_workspace_fields(workspace_id)

        ai_configured = self.newsletter_ai.is_configured()
        ai_payload: dict[str, Any] = {}
        if ai_configured:
            # The workspace's brand voice steers HOW the draft reads. Read
            # server-side per workspace and blended with the per-run user
            # guidance by the adapter — never fails a draft (port contract).
            voice: dict[str, str] = {}
            if self.brand_voice is not None:
                voice = self.brand_voice.get(str(workspace_id)) or {}
            ai_payload = (
                self.newsletter_ai.draft_newsletter(
                    workspace_id=str(workspace_id),
                    period_start=period_start,
                    period_end=period_end,
                    metrics=metrics,
                    user_guidance=user_guidance,
                    brand_voice=voice if (voice.get("tone") or voice.get("guidelines")) else None,
                )
                or {}
            )

        # SEE-174 — NO EMPTY SHELL. If the grounded planner path produced no
        # usable prose (agent unconfigured, LLM failure, or unparseable
        # output), fall back to a deterministic grounded summary built
        # straight from the enriched period metrics — never persist an empty
        # body. The summary's figures all come from ``metrics`` so they pass
        # the faithfulness verifier by construction.
        has_prose = bool((ai_payload.get("content_html") or "").strip()) or bool(
            ai_payload.get("sections")
        )
        used_fallback = False
        thin_data = False
        if not has_prose:
            from components.content.domain.services.newsletter_fallback_summary import (
                build as build_fallback_summary,
            )

            fallback = build_fallback_summary(
                workspace_name=workspace_name,
                period_start=period_start,
                period_end=period_end,
                metrics=metrics,
            )
            ai_payload = {
                **ai_payload,
                "title": fallback["title"],
                "content_html": fallback["content_html"],
                "sections": fallback["sections"],
            }
            used_fallback = True
            thin_data = bool(fallback.get("thin"))

        # Synthesize the layout block tree the FE editor / read-view
        # renders. Keeps the raw ``content_html`` + ``sections`` around so
        # the legacy renderer (and pre-blocks newsletter rows) still
        # work — the FE prefers ``layout.blocks`` when present.
        from components.content.domain.services.newsletter_block_composer import (
            compose as compose_newsletter_layout,
        )

        # (workspace_name / contact_email / mission resolved up-front.)

        # Resolve workspace-backed chart series. None if we can't compute
        # data — the composer drops the chart block from the tree.
        from components.content.domain.services.newsletter_chart_data import (
            donations_over_time,
        )
        from components.content.infrastructure.adapters.orm_donation_weekly_totals_adapter import (
            OrmDonationWeeklyTotalsAdapter,
        )

        chart_series = donations_over_time(
            workspace_id=workspace_id,
            period_end=period_end,
            repository=OrmDonationWeeklyTotalsAdapter(),
        )

        # The first sentence of the mission lands as the footer tagline
        # if the AI hasn't supplied one of its own. Cheap default; the
        # AI can override later by emitting ``footer_tagline``.
        mission_first_sentence = ""
        if workspace_mission:
            mission_first_sentence = workspace_mission.split(".")[0].strip()
            if mission_first_sentence and not mission_first_sentence.endswith("."):
                mission_first_sentence = f"{mission_first_sentence}."

        # Hero imagery: prefer the org's own cover photo, then its logo/photo,
        # then a deterministic curated stock photo so a newsletter is never a
        # bare text hero. The AI tool can still override via ``cover_image_url``.
        cover_image_url = (
            ai_payload.get("cover_image_url")
            or workspace_cover_photo_url
            or workspace_photo_url
            or _fallback_hero_image(workspace_id)
        )

        # Card-ify the flat text sections so the newsletter reads as punchy
        # cards (the reference design) rather than a wall of prose: promote
        # 'Thank you' to a two-column image card, turn 'Get involved' into the
        # CTA pill, and drop the prose that just restates the KPI cards.
        workspace_donate_url = (
            ai_payload.get("workspace_donate_url")
            or _workspace_donate_url(workspace_id)
            or None
        )
        thanks_image_url = workspace_photo_url or _fallback_thanks_image(workspace_id)
        cardified_sections, derived_cta_supporting = _cardify_sections(
            ai_payload.get("sections", []) or [],
            thanks_image_url=thanks_image_url,
            drop_kpi_prose=_kpi_metrics_present(metrics or {}),
            cta_available=bool(workspace_donate_url),
        )

        layout = compose_newsletter_layout(
            workspace_name=workspace_name,
            period_start=period_start,
            period_end=period_end,
            metrics=metrics,
            sections=cardified_sections,
            content_html=ai_payload.get("content_html", ""),
            cover_image_url=cover_image_url,
            workspace_donate_url=workspace_donate_url,
            chart_series=chart_series,
            image_blocks=ai_payload.get("image_blocks") or [],
            hero_accent_word=ai_payload.get("hero_accent_word", "") or "",
            cta_label=ai_payload.get("cta_label") or "Get Involved",
            cta_supporting=ai_payload.get("cta_supporting")
            or derived_cta_supporting
            or "",
            cta_tone=ai_payload.get("cta_tone") or "dark",
            footer_email=workspace_contact_email,
            footer_phone=ai_payload.get("footer_phone", "") or "",
            footer_website=ai_payload.get("footer_website", "") or "",
            footer_tagline=ai_payload.get("footer_tagline")
            or mission_first_sentence
            or "",
            footer_accent_tagline=ai_payload.get("footer_accent_tagline", "") or "",
            icon_divider_caption_html=ai_payload.get(
                "icon_divider_caption_html", ""
            )
            or "",
        )

        title = (
            ai_payload.get("title")
            or f"Newsletter — {period_start} to {period_end}"
        )
        content_html = ai_payload.get("content_html", "")
        # When the grounded summary fallback produced the body, there is no
        # authoring agent — record an empty agent so the editor labels it as
        # a system-generated summary, not an AI draft.
        if used_fallback:
            agent_type = ""
        else:
            agent_type = ai_payload.get("agent_type", "writing_agent")
        content_payload = {
            "metrics": metrics,
            "sections": ai_payload.get("sections", []),
            "agent_execution_id": ai_payload.get("agent_execution_id", ""),
            "layout": layout,
        }

        # Carry the source chunk identifiers from the deep-agent run so
        # the editor can surface "Drafted from N workspace sources" +
        # the operator can audit what the agent grounded against.
        # ``source_chunks`` falls back to [] when the adapter is the
        # legacy single-shot path or the planner didn't return them.
        source_chunks = ai_payload.get("source_chunks") or []
        metadata_dict: dict[str, Any] = {}
        if user_guidance:
            metadata_dict["user_guidance"] = user_guidance
        if source_chunks:
            metadata_dict["source_chunks"] = source_chunks
        if used_fallback:
            # Signals to the editor UI that this body is the deterministic
            # grounded summary, not an AI/agent draft — so it can show a
            # "regenerate" prompt and (when thin) a "thin data for this
            # period" banner instead of a blank shell.
            metadata_dict["grounded_fallback"] = True
            if not ai_configured:
                metadata_dict["ai_unconfigured"] = True
        if thin_data:
            metadata_dict["thin_data"] = True

        if existing is not None and force:
            # Overwrite the existing draft in place. Preserves the
            # newsletter UUID + subscriber list + period_start/end so
            # links and audit trails stay consistent.
            row = self.newsletter_store.replace_ai_draft(
                newsletter_id=existing.id,
                title=title,
                content_html=content_html,
                content_payload=content_payload,
                ai_drafted_by_agent=agent_type,
            )
        else:
            row = self.newsletter_store.create(
                workspace_id=workspace_id,
                title=title,
                content_html=content_html,
                status=NewsletterStatus.AI_DRAFTED,
                ai_drafted_by_agent=agent_type,
                period_start=period_start,
                period_end=period_end,
                content_payload=content_payload,
                metadata=metadata_dict or None,
            )
        self._emit_drafted(row, via_ai=not used_fallback)
        return row

    @staticmethod
    def _load_workspace_fields(workspace_id: UUID) -> tuple[str, str, str, str, str]:
        """Resolve (name, contact_email, mission, cover_photo_url, photo_url).

        Best-effort — a missing workspace or read error degrades to empty
        strings (the composer drops blocks it can't populate, the grounded
        summary falls back to a generic org label, and the hero falls back to
        a curated stock photo).
        """
        try:
            from infrastructure.persistence.workspaces.models import Workspace

            workspace = (
                Workspace.objects.filter(pk=workspace_id)
                .only(
                    "workspace_name",
                    "contact_email",
                    "mission",
                    "cover_photo_url",
                    "photo_url",
                )
                .first()
            )
            if workspace is not None:
                return (
                    workspace.workspace_name or "",
                    workspace.contact_email or "",
                    workspace.mission or "",
                    workspace.cover_photo_url or "",
                    workspace.photo_url or "",
                )
        except Exception:  # noqa: BLE001
            pass
        return "", "", "", "", ""

    def _emit_drafted(self, row: NewsletterEntity, *, via_ai: bool) -> None:
        self.event_publisher.publish(
            NewsletterDrafted(
                workspace_id=row.workspace_id,
                newsletter_id=row.id,
                title=row.title,
                via_ai=via_ai,
                author_id=None,
                agent_type=row.ai_drafted_by_agent,
                period_start=row.period_start,
                period_end=row.period_end,
            )
        )
