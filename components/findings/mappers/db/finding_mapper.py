"""Mechanical ORM ↔ domain translation for Finding. No business logic."""

from __future__ import annotations

from components.findings.domain.entities.finding_entity import FindingEntity
from components.shared_kernel.domain.security import FindingStatus, Severity
from components.shared_kernel.domain.tagging import TagRef


def _tag_refs(model) -> tuple[TagRef, ...]:
    """Project prefetched live tag links (``to_attr="prefetched_tag_links"`` — set
    only by the list read's ``Prefetch``, ADR 0015 D7) into read refs. A queryset
    that did not prefetch simply yields no tags — never a lazy per-row query."""
    links = getattr(model, "prefetched_tag_links", None)
    if not links:
        return ()
    return tuple(TagRef(id=link.tag.id, slug=link.tag.slug, name=link.tag.name, color=link.tag.color) for link in links)


def to_finding_entity(model) -> FindingEntity:
    return FindingEntity(
        id=model.id,
        workspace_id=model.workspace_id,
        source=model.source,
        fingerprint=model.fingerprint,
        asset_urn=model.asset_urn,
        severity=Severity.from_name(model.severity),
        status=FindingStatus(model.status),
        title=model.title,
        first_seen_at=model.first_seen_at,
        last_seen_at=model.last_seen_at,
        description=model.description,
        remediation=model.remediation,
        compliance=model.compliance or {},
        attributes=model.attributes or {},
        resolved_at=model.resolved_at,
        status_reason=model.status_reason,
        suppress_expires_at=model.suppress_expires_at,
        tags=_tag_refs(model),
    )


def to_finding_defaults(finding: FindingEntity) -> dict:
    """Field map for ``update_or_create(defaults=...)`` — the fields that a re-observation
    is allowed to mutate. Excludes the identity lookup keys (workspace, source,
    fingerprint) AND the insert-only fields (``id``, ``first_seen_at`` — see
    ``to_finding_create_defaults``), so an update never tries to rewrite the matched
    row's PK (which raises a UNIQUE violation) or reset when it was first observed.
    """
    return {
        "asset_urn": finding.asset_urn,
        "severity": finding.severity.value,
        "status": finding.status.value,
        "title": finding.title,
        "description": finding.description,
        "remediation": finding.remediation,
        "compliance": finding.compliance,
        "attributes": finding.attributes,
        "last_seen_at": finding.last_seen_at,
        "resolved_at": finding.resolved_at,
        "status_reason": finding.status_reason,
        "suppress_expires_at": finding.suppress_expires_at,
    }


def to_finding_create_defaults(finding: FindingEntity) -> dict:
    """Insert-only fields for ``update_or_create(create_defaults=...)`` — the entity's
    ``id`` and ``first_seen_at`` are applied ONLY when the row is created, never on an
    update. This makes upsert genuinely idempotent: re-observing (or re-seeding) never
    mutates the PK of the matched row."""
    return {
        **to_finding_defaults(finding),
        "id": finding.id,
        "first_seen_at": finding.first_seen_at,
    }
