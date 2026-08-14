"""Fitness function: exactly ONE tag vocabulary, and it is workspace-scoped.

ADR 0015 D2/D3 made ``tagging.Tag`` the canonical vocabulary, keyed by
``(workspace, slug)``. It did not remove the three inherited ones it replaced —
``workspaces.Tag``, ``project.Tag``, ``social.Tag`` — each a nonprofit-era
``#hashtag`` pool with a globally-unique name and no owner. All three survived
alongside the real one for months.

They were not inert. A workflow action node and an agent tool both called
``Tag.objects.get_or_create(name=...)`` with no workspace, so two tenants
automating the same tag name shared one row, and ``GET /workspaces/tags/``
served the pool to unauthenticated callers.

The tagging model's own docstring said "``workspaces.Tag`` … leaks tag
vocabularies across tenants and is being retired separately." A docstring
cannot fail a build. This test can: the next model named ``Tag``, or the next
relation pointed at something other than the canonical vocabulary, breaks here
rather than in a tenant's data.
"""

from __future__ import annotations

import pytest
from django.apps import apps

pytestmark = pytest.mark.arch

CANONICAL = ("tagging", "Tag")


def _tag_models():
    return [m for m in apps.get_models() if m.__name__ == "Tag"]


def test_only_one_model_is_named_tag():
    found = {(m._meta.app_label, m.__name__) for m in _tag_models()}
    assert found == {CANONICAL}, (
        f"Expected exactly one tag vocabulary ({CANONICAL[0]}.{CANONICAL[1]}), found: "
        f"{sorted(found)}. A second model named Tag is a parallel vocabulary — the "
        f"defect ADR 0015 exists to prevent. Point the relation at tagging.Tag instead."
    )


def test_the_canonical_vocabulary_is_workspace_scoped():
    """A vocabulary without an owner column cannot be tenant-isolated at all."""
    tag = apps.get_model(*CANONICAL)
    field_names = {f.name for f in tag._meta.get_fields()}
    assert "workspace" in field_names, (
        "tagging.Tag lost its workspace FK — every row would become global, "
        "which is exactly the shape of the three models this replaced."
    )


def test_the_canonical_vocabulary_is_unique_per_workspace_not_globally():
    """``name`` unique across the whole table = one tenant can deny another a tag
    name, and reveal that it uses it. Identity must be (workspace, slug)."""
    tag = apps.get_model(*CANONICAL)
    for field in tag._meta.fields:
        if field.name in {"name", "slug"}:
            assert not field.unique, (
                f"tagging.Tag.{field.name} is globally unique. Uniqueness belongs on "
                f"(workspace, slug) via a UniqueConstraint, not on the column."
            )

    scoped = [c for c in tag._meta.constraints if getattr(c, "fields", None) and "workspace" in c.fields]
    assert scoped, "tagging.Tag has no workspace-scoped uniqueness constraint."


def test_every_relation_to_a_tag_points_at_the_canonical_vocabulary():
    """Catches the reverse direction: a NEW model FK-ing some other tag table.

    ``test_only_one_model_is_named_tag`` would miss a vocabulary named
    ``Label`` or ``Keyword``; this catches any relation whose target owns a tag
    vocabulary that isn't the canonical one.
    """
    canonical = apps.get_model(*CANONICAL)
    offenders = []
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if not getattr(field, "many_to_many", False) and not getattr(field, "many_to_one", False):
                continue
            related = getattr(field, "related_model", None)
            if related is None or related.__name__ != "Tag":
                continue
            if related is not canonical:
                offenders.append(
                    f"{model._meta.app_label}.{model.__name__}.{field.name} -> "
                    f"{related._meta.app_label}.{related.__name__}"
                )
    assert not offenders, (
        f"These relations point at a tag model that is not the canonical workspace-scoped vocabulary: {offenders}"
    )
