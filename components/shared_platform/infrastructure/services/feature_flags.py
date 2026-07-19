from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db.models import Q
from django.utils import timezone

from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
from components.shared_platform.infrastructure.services.core_validators import ensure_uuid
from components.shared_platform.application.config.tier_features import features_for_tier
from components.shared_platform.infrastructure.adapters.django_cache_feature_flag_adapter import (
    DjangoCacheFeatureFlagAdapter,
)


def _workspace_plan_tier(workspace_id, request=None) -> str | None:
    """Resolve a workspace's subscription-tier title (e.g. ``"Pro"``).

    Reads ``Workspace.plan`` — the workspace's own subscription tier, which the
    billing flow sets on upgrade/downgrade. This is the single source of truth
    for "what tier is this workspace on". Intentionally NOT the subscription
    context's ``PlanQueryPort.get_plan_for_workspace`` (which resolves the
    workspace's *Team* plan for per-team entitlement *limits* — a different
    question); routing the gate through that would let the two diverge.

    Memoized per request so N flag evaluations in one request share a single
    ``Workspace`` lookup. Returns ``None`` when the workspace has no plan.
    """
    if not workspace_id:
        return None
    memo = None
    if request is not None:
        memo = getattr(request, "_ff_plan_tier_cache", None)
        if memo is None:
            memo = {}
            setattr(request, "_ff_plan_tier_cache", memo)
        if workspace_id in memo:
            return memo[workspace_id]
    from infrastructure.persistence.workspaces.models import Workspace

    tier = (
        Workspace.objects.filter(id=workspace_id)
        .values_list("plan__title", flat=True)
        .first()
    )
    if memo is not None:
        memo[workspace_id] = tier
    return tier


FEATURE_FLAGS_VERSION_CACHE_KEY = "feature_flags:v1:version"

_cache_adapter = DjangoCacheFeatureFlagAdapter()


@dataclass(frozen=True)
class FeatureFlagEvaluation:
    enabled: bool
    source: str


def _get_or_init_version() -> int:
    return _cache_adapter.get_version()


def bump_feature_flags_version() -> int:
    """
    Increment the global feature-flag cache version.

    This is preferred over scanning/deleting many per-flag keys.
    """
    return _cache_adapter.bump_version()


def _request_cache(request) -> dict[tuple[str, str | None, str | None], FeatureFlagEvaluation]:
    if request is None:
        return {}
    storage = getattr(request, "_feature_flag_cache", None)
    if storage is None:
        storage = {}
        setattr(request, "_feature_flag_cache", storage)
    return storage


def resolve_workspace_id_from_request(request, view=None) -> str | None:
    """
    Best-effort workspace resolution for feature flag evaluation.

    Priority:
    1) view.kwargs (`workspace_id` / `workspace`)
    2) query params (`workspace_id` / `workspace`)
    3) view.get_feature_flag_workspace_id(request) — resource-scoped resolver
       (e.g. a draft/newsletter endpoint resolves the flag against the
       resource's OWN workspace, not the user's active workspace)
    4) authenticated user's profile active_workspace_id

    The view hook (3) deliberately precedes the active-workspace fallback (4):
    when an endpoint operates on a workspace-owned resource whose workspace is
    not in the URL, the flag MUST be evaluated against that resource's
    workspace. Falling back to the user's active workspace there resolves the
    flag against the wrong workspace and can silently 403 a permitted action
    (the AI-writing draft-with-ai bug: a member viewing a draft in workspace B
    while their active workspace A lacks the flag was wrongly denied).
    """
    workspace_id = None
    if view is not None:
        kwargs = getattr(view, "kwargs", {}) or {}
        workspace_id = kwargs.get("workspace_id") or kwargs.get("workspace")

    if not workspace_id and request is not None:
        qp = getattr(request, "query_params", None) or getattr(request, "GET", {})
        workspace_id = qp.get("workspace_id") or qp.get("workspace")

    if not workspace_id and view is not None:
        resolver = getattr(view, "get_feature_flag_workspace_id", None)
        if callable(resolver):
            workspace_id = resolver(request)

    if not workspace_id and request is not None:
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            profile = getattr(user, "profile", None)
            active = getattr(profile, "active_workspace_id", None) if profile else None
            workspace_id = str(active) if active else None

    return str(workspace_id) if workspace_id else None


def evaluate_feature_flag(
    flag_key: str,
    *,
    user=None,
    workspace_id: str | None = None,
    request=None,
) -> FeatureFlagEvaluation:
    """
    Evaluate a single flag for a given user/workspace context.

    Resolution order:
      user -> workspace -> plan tier -> global -> FeatureFlag.default_enabled
    (the plan-tier layer unlocks a paid tier's feature set above the global
    default but below explicit user/workspace rules — see step 2.5 below.)
    """
    normalized_flag_key = FeatureFlag.normalize_key(flag_key)
    if not normalized_flag_key:
        return FeatureFlagEvaluation(enabled=False, source="invalid_key")

    normalized_workspace_id: str | None = None
    if workspace_id:
        try:
            normalized_workspace_id = str(ensure_uuid(workspace_id, field_name="workspace_id"))
        except Exception:
            normalized_workspace_id = None

    user_id = str(getattr(user, "id", "") or "") if user else None
    cache_key = (normalized_flag_key, user_id or None, normalized_workspace_id or None)

    per_request = _request_cache(request)
    if per_request and cache_key in per_request:
        return per_request[cache_key]

    version = _get_or_init_version()
    shared_key = (
        f"feature_flags:v1:{normalized_flag_key}:u:{user_id or 'anon'}:"
        f"w:{normalized_workspace_id or 'none'}:v:{version}"
    )
    cached = _cache_adapter.get_evaluation(shared_key)
    if isinstance(cached, dict) and "enabled" in cached and "source" in cached:
        result = FeatureFlagEvaluation(enabled=bool(cached["enabled"]), source=str(cached["source"]))
        if per_request is not None:
            per_request[cache_key] = result
        return result

    flag = FeatureFlag.objects.filter(key=normalized_flag_key).only("id", "default_enabled").first()
    if not flag:
        result = FeatureFlagEvaluation(enabled=False, source="missing_flag")
        _cache_adapter.set_evaluation(shared_key, {"enabled": result.enabled, "source": result.source}, timeout=300)
        if per_request is not None:
            per_request[cache_key] = result
        return result

    now = timezone.now()

    # 1) User-level override
    if user and user_id:
        rule = (
            FeatureFlagRule.objects.filter(flag_id=flag.id, scope=FeatureFlagRule.Scope.USER, user_id=user_id)
            .only("enabled", "starts_at", "ends_at")
            .first()
        )
        if rule and rule.is_active_now(now):
            result = FeatureFlagEvaluation(enabled=bool(rule.enabled), source="user_rule")
            _cache_adapter.set_evaluation(shared_key, {"enabled": result.enabled, "source": result.source}, timeout=300)
            if per_request is not None:
                per_request[cache_key] = result
            return result

    # 2) Workspace-level override
    if normalized_workspace_id:
        rule = (
            FeatureFlagRule.objects.filter(
                flag_id=flag.id,
                scope=FeatureFlagRule.Scope.WORKSPACE,
                workspace_id=normalized_workspace_id,
            )
            .only("enabled", "starts_at", "ends_at")
            .first()
        )
        if rule and rule.is_active_now(now):
            result = FeatureFlagEvaluation(enabled=bool(rule.enabled), source="workspace_rule")
            _cache_adapter.set_evaluation(shared_key, {"enabled": result.enabled, "source": result.source}, timeout=300)
            if per_request is not None:
                per_request[cache_key] = result
            return result

    # 2.5) Plan-tier unlock — a paid tier turns its feature set ON, above the
    # global default but below explicit user/workspace rules (already checked).
    # Only unlocks (never disables); non-tier flags fall through unchanged.
    if normalized_workspace_id:
        tier = _workspace_plan_tier(normalized_workspace_id, request)
        if normalized_flag_key in features_for_tier(tier):
            result = FeatureFlagEvaluation(enabled=True, source="plan_tier")
            _cache_adapter.set_evaluation(shared_key, {"enabled": result.enabled, "source": result.source}, timeout=300)
            if per_request is not None:
                per_request[cache_key] = result
            return result

    # 3) Global override
    rule = (
        FeatureFlagRule.objects.filter(flag_id=flag.id, scope=FeatureFlagRule.Scope.GLOBAL)
        .only("enabled", "starts_at", "ends_at")
        .first()
    )
    if rule and rule.is_active_now(now):
        result = FeatureFlagEvaluation(enabled=bool(rule.enabled), source="global_rule")
        _cache_adapter.set_evaluation(shared_key, {"enabled": result.enabled, "source": result.source}, timeout=300)
        if per_request is not None:
            per_request[cache_key] = result
        return result

    # 4) Default
    result = FeatureFlagEvaluation(enabled=bool(flag.default_enabled), source="default")
    _cache_adapter.set_evaluation(shared_key, {"enabled": result.enabled, "source": result.source}, timeout=300)
    if per_request is not None:
        per_request[cache_key] = result
    return result


def is_feature_enabled(
    flag_key: str,
    *,
    user=None,
    workspace_id: str | None = None,
    request=None,
) -> bool:
    return evaluate_feature_flag(flag_key, user=user, workspace_id=workspace_id, request=request).enabled


def flags_for_context(
    *,
    user=None,
    workspace_id: str | None = None,
    include_sources: bool = False,
    request=None,
) -> dict[str, Any]:
    """
    Return a map of all known flags evaluated for the given context.

    Intended for frontend bootstrapping; avoid calling in hot loops.
    """
    version = _get_or_init_version()
    normalized_workspace_id = None
    if workspace_id:
        try:
            normalized_workspace_id = str(ensure_uuid(workspace_id, field_name="workspace_id"))
        except Exception:
            normalized_workspace_id = None

    now = timezone.now()
    user_id = getattr(user, "id", None) if user else None

    shared_key = (
        f"feature_flags:v1:map:u:{str(user_id) if user_id else 'anon'}:"
        f"w:{normalized_workspace_id or 'none'}:v:{version}:sources:{int(bool(include_sources))}"
    )
    cached = _cache_adapter.get_evaluation(shared_key)
    if isinstance(cached, dict):
        return cached

    flags = list(FeatureFlag.objects.all().only("id", "key", "default_enabled"))
    if not flags:
        return {}

    scope_filter = Q(scope=FeatureFlagRule.Scope.GLOBAL)
    if normalized_workspace_id:
        scope_filter |= Q(scope=FeatureFlagRule.Scope.WORKSPACE, workspace_id=normalized_workspace_id)
    if user_id:
        scope_filter |= Q(scope=FeatureFlagRule.Scope.USER, user_id=user_id)

    rules = list(
        FeatureFlagRule.objects.filter(flag_id__in=[flag.id for flag in flags])
        .filter(scope_filter)
        .select_related("flag")
        .only("flag_id", "scope", "enabled", "starts_at", "ends_at", "workspace_id", "user_id")
    )

    global_rules = {}
    workspace_rules = {}
    user_rules = {}
    for rule in rules:
        if not rule.is_active_now(now):
            continue
        if rule.scope == FeatureFlagRule.Scope.GLOBAL:
            global_rules[rule.flag_id] = rule
        elif rule.scope == FeatureFlagRule.Scope.WORKSPACE and normalized_workspace_id and str(rule.workspace_id) == normalized_workspace_id:
            workspace_rules[rule.flag_id] = rule
        elif rule.scope == FeatureFlagRule.Scope.USER and user_id and str(rule.user_id) == str(user_id):
            user_rules[rule.flag_id] = rule

    # Plan-tier unlock set for this workspace — one lookup for the whole map.
    tier_unlocked = features_for_tier(
        _workspace_plan_tier(normalized_workspace_id, request)
    )

    results: dict[str, Any] = {}
    for flag in flags:
        if flag.id in user_rules:
            enabled = bool(user_rules[flag.id].enabled)
            source = "user_rule"
        elif flag.id in workspace_rules:
            enabled = bool(workspace_rules[flag.id].enabled)
            source = "workspace_rule"
        elif flag.key in tier_unlocked:
            enabled = True
            source = "plan_tier"
        elif flag.id in global_rules:
            enabled = bool(global_rules[flag.id].enabled)
            source = "global_rule"
        else:
            enabled = bool(flag.default_enabled)
            source = "default"

        if include_sources:
            results[flag.key] = {"enabled": enabled, "source": source}
        else:
            results[flag.key] = enabled

    _cache_adapter.set_evaluation(shared_key, results, timeout=300)
    return results
