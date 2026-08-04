"""Django adapter implementing TagStorePort (ADR 0015).

Enforcement of the vocabulary invariants (normalization, reserved/system
protection, count limits) lives behind the port so BOTH entry paths — the CRUD
use cases and the findings tag/untag auto-create — hit one implementation. The
rules themselves are domain functions/constants (``tag_slug``, ``constants``);
this adapter only applies them at the persistence seam.
"""

from __future__ import annotations

import uuid as uuid_module
from collections.abc import Sequence
from uuid import UUID

from components.shared_kernel.domain.tagging import TagRef
from components.tagging.application.commands.create_tag_command import CreateTagCommand
from components.tagging.application.commands.update_tag_command import UpdateTagCommand
from components.tagging.application.ports.tag_store_port import TagStorePort
from components.tagging.domain.constants import (
    KIND_SYSTEM,
    KIND_USER,
    MAX_LIVE_TAGS_PER_WORKSPACE,
    RESERVED_NAMESPACES,
    is_system_only_namespace,
)
from components.tagging.domain.entities.tag_entity import TagEntity
from components.tagging.domain.errors import (
    DuplicateTagError,
    ReservedTagError,
    TagLimitExceededError,
    TagNotFoundError,
)
from components.tagging.domain.value_objects.tag_slug import (
    ParsedTag,
    parse,
    try_normalize_slug,
    validate_color,
)
from components.tagging.mappers.db.tag_mapper import to_tag_entity


class DjangoTagRepository(TagStorePort):
    # ── Reads ──────────────────────────────────────────────────────────

    def resolve_slugs(self, workspace_id: UUID, slugs: Sequence[str]) -> dict[str, UUID]:
        from infrastructure.persistence.tagging.models import Tag

        normalized = [s for s in (try_normalize_slug(raw) for raw in slugs) if s is not None]
        if not normalized:
            return {}
        rows = Tag.active.filter(workspace_id=workspace_id, slug__in=normalized).values_list("slug", "id")
        return dict(rows)

    def refs_for_ids(self, workspace_id: UUID, tag_ids: Sequence[UUID]) -> tuple[TagRef, ...]:
        from infrastructure.persistence.tagging.models import Tag

        if not tag_ids:
            return ()
        rows = Tag.active.filter(workspace_id=workspace_id, id__in=list(tag_ids)).order_by("slug")
        return tuple(TagRef(id=t.id, slug=t.slug, name=t.name, color=t.color) for t in rows)

    def get_by_id(self, workspace_id: UUID, tag_id: UUID) -> TagEntity:
        obj = self._get_model(workspace_id, tag_id)
        return to_tag_entity(obj)

    def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        namespace: str | None = None,
        q: str | None = None,
        with_usage: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[TagEntity], int]:
        from django.db.models import Count, Q

        from infrastructure.persistence.tagging.models import Tag

        qs = Tag.active.filter(workspace_id=workspace_id)
        if namespace is not None:
            qs = qs.filter(namespace=namespace)
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q))
        total = qs.count()
        if with_usage:
            # One annotate in the repository — never a per-row query (perf rule §9).
            qs = qs.annotate(usage_count=Count("finding_links"))
        rows = qs.order_by("slug")[offset : offset + limit]
        return [to_tag_entity(obj) for obj in rows], total

    # ── Writes ─────────────────────────────────────────────────────────

    def get_or_create(self, workspace_id: UUID, raw: str, *, kind: str = KIND_USER) -> TagEntity:
        from infrastructure.persistence.tagging.models import Tag

        parsed = parse(raw)
        self._guard_system_namespace(parsed, kind=kind)

        existing = Tag.active.filter(workspace_id=workspace_id, slug=parsed.slug).first()
        if existing is not None:
            if existing.kind == KIND_SYSTEM and kind != KIND_SYSTEM:
                # Apply-by-name of a system tag is platform-only (D4).
                raise ReservedTagError(f"Tag {parsed.slug!r} is platform-managed (system).")
            return to_tag_entity(existing)

        self._guard_workspace_limit(workspace_id)
        obj = self._create_row(workspace_id, parsed, color="", description="", kind=kind)
        return to_tag_entity(obj)

    def create(self, command: CreateTagCommand) -> TagEntity:
        from infrastructure.persistence.tagging.models import Tag

        parsed = parse(command.name, namespace=command.namespace)
        self._guard_system_namespace(parsed, kind=command.kind)
        validate_color(command.color)

        if Tag.active.filter(workspace_id=command.workspace_id, slug=parsed.slug).exists():
            raise DuplicateTagError(f"A live tag with slug {parsed.slug!r} already exists.")
        self._guard_workspace_limit(command.workspace_id)

        obj = self._create_row(
            command.workspace_id,
            parsed,
            color=command.color,
            description=command.description,
            kind=command.kind,
            on_conflict="raise",
        )
        return to_tag_entity(obj)

    def update(self, command: UpdateTagCommand) -> TagEntity:
        from infrastructure.persistence.tagging.models import Tag

        obj = self._get_model(command.workspace_id, command.tag_id)
        if obj.kind == KIND_SYSTEM:
            raise ReservedTagError("System tags are platform-managed and cannot be edited.")

        if command.name is not None:
            parsed = parse(command.name)
            self._guard_system_namespace(parsed, kind=obj.kind)
            if parsed.namespace != obj.namespace and (
                obj.namespace in RESERVED_NAMESPACES or parsed.namespace in RESERVED_NAMESPACES
            ):
                # D5: rename may move a tag only between "" and a NON-reserved
                # namespace — reserved-namespace membership never changes via rename.
                raise ReservedTagError("Rename cannot move a tag into or out of a reserved namespace.")
            obj.name = parsed.name
            obj.slug = parsed.slug
            obj.namespace = parsed.namespace
        if command.color is not None:
            obj.color = validate_color(command.color)
        if command.description is not None:
            obj.description = command.description
        if command.is_deleted is not None:
            obj.is_deleted = command.is_deleted

        if not obj.is_deleted:
            # Live-identity re-check: covers rename AND restore (D5).
            clash = Tag.active.filter(workspace_id=command.workspace_id, slug=obj.slug).exclude(id=obj.id).exists()
            if clash:
                raise DuplicateTagError(f"A live tag with slug {obj.slug!r} already exists.")

        obj.save()
        return to_tag_entity(obj)

    def soft_delete(self, workspace_id: UUID, tag_id: UUID) -> None:
        obj = self._get_model(workspace_id, tag_id)
        if obj.kind == KIND_SYSTEM:
            raise ReservedTagError("System tags are platform-managed and cannot be deleted.")
        if not obj.is_deleted:
            obj.is_deleted = True
            obj.save(update_fields=["is_deleted", "updated_at"])

    # ── Internals ──────────────────────────────────────────────────────

    @staticmethod
    def _get_model(workspace_id: UUID, tag_id: UUID):
        from infrastructure.persistence.tagging.models import Tag

        obj = Tag.objects.filter(workspace_id=workspace_id, id=tag_id).first()
        if obj is None:
            raise TagNotFoundError(f"Tag {tag_id} not found in workspace {workspace_id}.")
        return obj

    @staticmethod
    def _guard_system_namespace(parsed: ParsedTag, *, kind: str) -> None:
        if is_system_only_namespace(parsed.namespace) and kind != KIND_SYSTEM:
            raise ReservedTagError(f"The {parsed.namespace!r} namespace is reserved for the platform.")

    @staticmethod
    def _guard_workspace_limit(workspace_id: UUID) -> None:
        from infrastructure.persistence.tagging.models import Tag

        if Tag.active.filter(workspace_id=workspace_id).count() >= MAX_LIVE_TAGS_PER_WORKSPACE:
            raise TagLimitExceededError(
                f"Workspace vocabulary limit reached ({MAX_LIVE_TAGS_PER_WORKSPACE} live tags)."
            )

    @staticmethod
    def _create_row(
        workspace_id: UUID,
        parsed: ParsedTag,
        *,
        color: str,
        description: str,
        kind: str,
        on_conflict: str = "return",
    ):
        """Insert one Tag row. A concurrent create of the same live slug loses the
        race against ``uniq_tag_ws_slug_live``; ``on_conflict`` picks the caller's
        semantics — ``"return"`` the winner (get_or_create) or ``"raise"``
        DuplicateTagError (explicit create)."""
        from django.db import IntegrityError

        from infrastructure.persistence.tagging.models import Tag

        try:
            return Tag.objects.create(
                id=uuid_module.uuid4(),
                workspace_id=workspace_id,
                name=parsed.name,
                slug=parsed.slug,
                namespace=parsed.namespace,
                color=color,
                description=description,
                kind=kind,
            )
        except IntegrityError:
            existing = Tag.active.filter(workspace_id=workspace_id, slug=parsed.slug).first()
            if existing is None:
                raise
            if on_conflict == "raise":
                raise DuplicateTagError(f"A live tag with slug {parsed.slug!r} already exists.")
            return existing
