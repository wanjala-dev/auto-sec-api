"""Unit tests for TagFindingUseCase (no DB — in-memory port doubles). ADR 0015 D6."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.findings.application.commands.tag_finding_command import TagFindingCommand
from components.findings.application.use_cases.tag_finding_use_case import TagFindingUseCase
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.domain.errors import FindingNotFoundError
from components.shared_kernel.domain.security import FindingStatus, Severity
from components.shared_kernel.domain.tagging import TagRef
from components.tagging.domain.entities.tag_entity import TagEntity
from components.tagging.domain.errors import ReservedTagError, TagLimitExceededError
from components.tagging.domain.value_objects.tag_slug import parse

pytestmark = [pytest.mark.unit]

NOW = datetime(2026, 8, 3, tzinfo=UTC)


class _FakeFindingStore:
    def __init__(self, finding: FindingEntity | None = None):
        self._by_id = {}
        if finding is not None:
            self._by_id[(finding.workspace_id, finding.id)] = finding

    def find_by_id(self, workspace_id, finding_id):
        return self._by_id.get((workspace_id, finding_id))


class _FakeTagStore:
    """In-memory TagStorePort double: normalizes via the real domain functions."""

    def __init__(self):
        self._by_slug: dict[str, TagEntity] = {}

    def get_or_create(self, workspace_id, raw, *, kind="user"):
        parsed = parse(raw)
        if parsed.namespace == "risk" and kind != "system":
            raise ReservedTagError("risk: is platform-only")
        if parsed.slug not in self._by_slug:
            self._by_slug[parsed.slug] = TagEntity(
                id=uuid4(),
                workspace_id=workspace_id,
                name=parsed.name,
                slug=parsed.slug,
                namespace=parsed.namespace,
                kind=kind,
            )
        return self._by_slug[parsed.slug]

    def resolve_slugs(self, workspace_id, slugs):
        out = {}
        for raw in slugs:
            try:
                slug = parse(raw).slug
            except Exception:
                continue
            if slug in self._by_slug:
                out[slug] = self._by_slug[slug].id
        return out


class _FakeLinkStore:
    def __init__(self):
        self.links: dict[tuple, set] = {}
        self._refs_by_id: dict = {}

    def _key(self, workspace_id, finding_id):
        return (workspace_id, finding_id)

    def tag_ids_for_finding(self, workspace_id, finding_id):
        return set(self.links.get(self._key(workspace_id, finding_id), set()))

    def add_tags(self, workspace_id, finding_id, tag_ids, *, actor_id, source="user"):
        self.links.setdefault(self._key(workspace_id, finding_id), set()).update(tag_ids)

    def remove_tags(self, workspace_id, finding_id, tag_ids):
        self.links.setdefault(self._key(workspace_id, finding_id), set()).difference_update(tag_ids)

    def refs_for_finding(self, workspace_id, finding_id):
        ids = self.links.get(self._key(workspace_id, finding_id), set())
        return tuple(
            TagRef(id=tag_id, slug=f"slug-{i}", name=f"name-{i}", color="")
            for i, tag_id in enumerate(sorted(ids, key=str))
        )


def _finding() -> FindingEntity:
    return FindingEntity(
        id=uuid4(),
        workspace_id=uuid4(),
        source="cloud_posture.prowler",
        fingerprint="fp-1",
        asset_urn="arn:aws:s3:::bucket",
        severity=Severity.HIGH,
        status=FindingStatus.OPEN,
        title="Public bucket",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


def _use_case(finding=None):
    finding_store = _FakeFindingStore(finding)
    tag_store = _FakeTagStore()
    link_store = _FakeLinkStore()
    return (
        TagFindingUseCase(finding_store=finding_store, tag_store=tag_store, link_store=link_store),
        tag_store,
        link_store,
    )


def _cmd(finding, *, add=(), remove=()):
    return TagFindingCommand(
        workspace_id=finding.workspace_id,
        finding_id=finding.id,
        add=tuple(add),
        remove=tuple(remove),
        actor_id="actor-1",
        at=NOW,
    )


class TestTagFindingUseCase:
    def test_add_auto_creates_and_links(self):
        f = _finding()
        use_case, tag_store, link_store = _use_case(f)
        result = use_case.execute(_cmd(f, add=["env:prod", "needs-review"]))
        assert len(result.tags) == 2
        assert set(tag_store._by_slug) == {"env:prod", "needs-review"}
        assert len(link_store.tag_ids_for_finding(f.workspace_id, f.id)) == 2

    def test_remove_unknown_slug_is_noop(self):
        f = _finding()
        use_case, _, link_store = _use_case(f)
        result = use_case.execute(_cmd(f, add=["env:prod"], remove=["never-existed"]))
        assert len(result.tags) == 1

    def test_add_and_remove_in_one_call(self):
        f = _finding()
        use_case, _, link_store = _use_case(f)
        use_case.execute(_cmd(f, add=["team:payments"]))
        use_case.execute(_cmd(f, add=["env:prod"], remove=["team:payments"]))
        assert len(link_store.tag_ids_for_finding(f.workspace_id, f.id)) == 1

    def test_missing_finding_raises_not_found(self):
        f = _finding()
        use_case, _, _ = _use_case(None)
        with pytest.raises(FindingNotFoundError):
            use_case.execute(_cmd(f, add=["env:prod"]))

    def test_risk_namespace_rejected(self):
        f = _finding()
        use_case, _, _ = _use_case(f)
        with pytest.raises(ReservedTagError):
            use_case.execute(_cmd(f, add=["risk:accepted"]))

    def test_per_finding_cap_enforced(self):
        f = _finding()
        use_case, _, _ = _use_case(f)
        use_case.execute(_cmd(f, add=[f"tag-{i}" for i in range(50)]))
        with pytest.raises(TagLimitExceededError):
            use_case.execute(_cmd(f, add=["one-more"]))

    def test_cap_accounts_for_simultaneous_removes(self):
        f = _finding()
        use_case, _, _ = _use_case(f)
        use_case.execute(_cmd(f, add=[f"tag-{i}" for i in range(50)]))
        # Swapping one out while adding one keeps the prospective set at 50 — allowed.
        result = use_case.execute(_cmd(f, add=["one-more"], remove=["tag-0"]))
        assert len(result.tags) == 50
