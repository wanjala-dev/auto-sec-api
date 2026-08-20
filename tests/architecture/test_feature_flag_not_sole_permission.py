"""Architecture guardrail: a feature flag is never the only permission class.

``RequiresFeatureFlag`` answers "is this capability switched on?" — never "is
this caller allowed to touch this object?". Listing it alone in a view's
``permission_classes`` is a security defect, because three things compound:

1. Declaring ``permission_classes`` REPLACES the project default
   (``DEFAULT_PERMISSION_CLASSES`` = IsAdminUser + IsAuthenticated,
   ``api/settings/base.py``), so the usual auth backstop is gone.
2. ``RequiresFeatureFlag`` defines no ``has_object_permission``, so DRF's
   object-level check passes by default — every object is reachable.
3. ``resolve_workspace_id_from_request`` honours a caller-supplied
   ``?workspace_id=`` / ``?workspace=`` query param, so an *unauthenticated*
   caller chooses which workspace the flag is evaluated against and can point
   it at any workspace that has the flag on.

Net effect when the class stands alone on a write endpoint: an anonymous
request passes the entire permission chain.

This is not hypothetical. ``components/social/api/controller.py::PostDetail``
(``/social/<int:pk>/``, a ``RetrieveUpdateDestroyAPIView``) shipped with
``permission_classes = (RequiresFeatureFlag,)`` and was reproduced live as an
unauthenticated cross-tenant update and **hard delete** of any user's post.

A docstring alone would not have caught this — that is why this file exists.

Opting out
----------
An endpoint that is genuinely public by design adds itself to
``DELIBERATELY_PUBLIC`` below WITH a written justification. Adding an entry is
a security decision and should be reviewed as one. The wrong fix is to silence
this test; the right fix is almost always to add the missing auth class.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = ROOT / "components"

FLAG_PERMISSION = "RequiresFeatureFlag"

# ``"<path relative to repo root>::<ViewClassName>"`` → why it is safe alone.
#
# Every entry must explain (a) why unauthenticated access is intended and
# (b) what enforces authorization instead of the permission class.
DELIBERATELY_PUBLIC: dict[str, str] = {
    "components/agents/api/controller.py::SharedAgentViewSet": (
        "Public share-link endpoint: the unguessable share token in the URL IS the "
        "credential, so requiring a session would defeat the feature. Authorization "
        "is enforced below the view rather than by a permission class — "
        "AgentEngagementQueryRepository.get_shared_agent() rejects a missing, expired "
        "or revoked token and a disabled agent profile (404), and demands an "
        "authenticated workspace member when the share scope is 'workspace_only'; the "
        "DELETE/revoke path runs AgentAIPermission with required_ai_perm='ai_manage', "
        "which denies anonymous callers outright (pinned by "
        "components/agents/tests/unit/test_agent_ai_permission_denies_anonymous.py). "
        "Separately, and NOT the reason for this exemption: the viewset is currently "
        "unroutable — its only method is named 'shared_agent', which DefaultRouter "
        "does not map and which carries no @action decorator, so /ai/agents/shared/ "
        "returns a Django 404 while sibling /ai/agents/ routes 401 (verified against "
        "the live cluster 2026-08-19). If it is ever wired up, the enforcement above "
        "is what must hold."
    ),
}


def _permission_class_names(node: ast.ClassDef) -> list[str] | None:
    """Return the names listed in a class's ``permission_classes``, if declared."""
    for statement in node.body:
        if not isinstance(statement, ast.Assign):
            continue
        targets = [t.id for t in statement.targets if isinstance(t, ast.Name)]
        if "permission_classes" not in targets:
            continue
        value = statement.value
        if not isinstance(value, (ast.Tuple, ast.List)):
            # A computed value (e.g. a call or a name) — not statically checkable.
            return None
        names: list[str] = []
        for element in value.elts:
            if isinstance(element, ast.Name):
                names.append(element.id)
            elif isinstance(element, ast.Attribute):
                names.append(element.attr)
            elif isinstance(element, ast.Call):
                func = element.func
                names.append(func.id if isinstance(func, ast.Name) else getattr(func, "attr", "?"))
        return names
    return None


def _controllers() -> list[Path]:
    return sorted(p for p in COMPONENTS.rglob("*.py") if "/tests/" not in p.as_posix())


def _offenders() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in _controllers():
        source = path.read_text(encoding="utf-8")
        if FLAG_PERMISSION not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names = _permission_class_names(node)
            if names is None:
                continue
            if names == [FLAG_PERMISSION]:
                rel = path.relative_to(ROOT).as_posix()
                found.append((f"{rel}::{node.name}", node.name))
    return found


def test_requires_feature_flag_is_never_the_only_permission_class():
    offenders = [key for key, _ in _offenders() if key not in DELIBERATELY_PUBLIC]

    assert not offenders, (
        "These views list RequiresFeatureFlag as their ONLY permission class, which "
        "replaces the project default and leaves a feature flag as the sole gate — "
        "an unauthenticated caller can satisfy it with ?workspace_id=<any enabled "
        "workspace>. Compose it with IsAuthenticated (plus an object-level class for "
        "detail views), or register a justified exemption in DELIBERATELY_PUBLIC:\n  " + "\n  ".join(sorted(offenders))
    )


def test_public_exemptions_are_still_real_and_justified():
    """Keep the allowlist honest — stale entries hide the next regression."""
    live = {key for key, _ in _offenders()}
    stale = sorted(set(DELIBERATELY_PUBLIC) - live)

    assert not stale, (
        "DELIBERATELY_PUBLIC lists views that no longer use RequiresFeatureFlag alone. "
        "Remove them so the allowlist cannot silently pre-approve a future regression:\n  " + "\n  ".join(stale)
    )

    unjustified = sorted(key for key, why in DELIBERATELY_PUBLIC.items() if len(why.strip()) < 80)
    assert not unjustified, (
        "Every DELIBERATELY_PUBLIC entry needs a real justification naming what enforces "
        "authorization instead:\n  " + "\n  ".join(unjustified)
    )


def _declared_permissions(rel_path: str, class_name: str) -> list[str]:
    tree = ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return _permission_class_names(node) or []
    raise AssertionError(f"{class_name} not found in {rel_path}")


@pytest.mark.parametrize(
    "class_name",
    ["PostList", "PostDetail", "CommentList", "CommentDetail"],
)
def test_legacy_social_crud_surface_requires_authentication(class_name):
    """Regression pin for the views that were anonymously reachable.

    ``PostDetail`` was the unauthenticated cross-tenant write; the other three
    carried ``IsAuthenticatedOrReadOnly`` over a workspace-unscoped queryset,
    which served every tenant's posts and comments to an anonymous GET.

    Kept as an AST check (not an import) because this package's conftest
    documents architecture tests as pure source scanners with ORM access
    blocked — importing the controller runs its module-level provider wiring.
    """
    names = _declared_permissions("components/social/api/controller.py", class_name)

    assert "IsAuthenticated" in names, f"{class_name} must require authentication; got {names}"
    assert "IsAuthenticatedOrReadOnly" not in names, (
        f"{class_name} serves a workspace-unscoped queryset — 'or read only' means "
        f"anonymous cross-tenant reads; got {names}"
    )
    assert "IsOwnerOrReadOnly" in names, f"{class_name} must enforce object ownership; got {names}"
    assert FLAG_PERMISSION in names, f"{class_name} must keep its feature gate; got {names}"
