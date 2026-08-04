"""Unit tests for TagEntity invariants (frozen dataclass, ADR 0015 D3)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.tagging.domain.entities.tag_entity import TagEntity

pytestmark = [pytest.mark.unit]


def _entity(**overrides) -> TagEntity:
    defaults = dict(
        id=uuid4(),
        workspace_id=uuid4(),
        name="Prod",
        slug="env:prod",
        namespace="env",
        color="#FF0000",
        kind="user",
    )
    defaults.update(overrides)
    return TagEntity(**defaults)


class TestTagEntity:
    def test_valid_entity(self):
        tag = _entity()
        assert tag.slug == "env:prod"
        assert not tag.is_system

    def test_to_ref_carries_identity_and_display(self):
        tag = _entity()
        ref = tag.to_ref()
        assert (ref.id, ref.slug, ref.name, ref.color) == (tag.id, "env:prod", "Prod", "#FF0000")

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            _entity(name="  ")

    def test_overlong_name_rejected(self):
        with pytest.raises(ValueError):
            _entity(name="x" * 65)

    def test_unnormalized_slug_rejected(self):
        with pytest.raises(ValueError):
            _entity(slug="Env:Prod")

    def test_slug_must_carry_namespace_prefix(self):
        with pytest.raises(ValueError):
            _entity(slug="prod")  # namespace="env" but slug is flat

    def test_invalid_namespace_rejected(self):
        with pytest.raises(ValueError):
            _entity(namespace="9bad", slug="9bad:prod")

    def test_invalid_color_rejected(self):
        with pytest.raises(ValueError):
            _entity(color="red")

    def test_invalid_kind_rejected(self):
        with pytest.raises(ValueError):
            _entity(kind="magic")

    def test_system_kind(self):
        assert _entity(kind="system").is_system

    def test_immutable(self):
        tag = _entity()
        with pytest.raises(AttributeError):
            tag.name = "other"  # type: ignore[misc]
