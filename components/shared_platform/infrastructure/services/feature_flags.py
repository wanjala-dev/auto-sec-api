from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from django.db.models import Q
from django.utils import timezone

from components.shared_platform.application.config.tier_features import features_for_tier
from components.shared_platform.infrastructure.adapters.django_cache_feature_flag_adapter import (
    DjangoCacheFeatureFlagAdapter,
)
from components.shared_platform.infrastructure.services.core_validators import ensure_uuid
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule


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
            request._ff_plan_tier_cache = memo
        if workspace_id in memo:
            return memo[workspace_id]
    from infrastructure.persistence.workspaces.models import Workspace

    tier = Workspace.objects.filter(id=workspace_id).values_list("plan__title", flat=True).first()
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


def set_workspace_flag(flag_key: str, workspace_id, enabled: bool, *, updated_by_id=None, note: str = ""):
    """Create/update the WORKSPACE-scoped rule for ``flag_key`` on ``workspace_id`` and
    invalidate the cache. The single programmatic entry point for toggling a per-workspace
    flag (used by the sample-data-mode owner toggle, ADR 0011). Idempotent."""
    flag, _ = FeatureFlag.objects.get_or_create(
        key=flag_key,
        defaults={"default_enabled": False, "description": ""},
    )
    rule, _ = FeatureFlagRule.objects.update_or_create(
        flag=flag,
        scope=FeatureFlagRule.Scope.WORKSPACE,
        workspace_id=workspace_id,
        defaults={"enabled": enabled, "updated_by_id": updated_by_id, "note": note},
    )
    bump_feature_flags_version()
    return rule


def _request_cache(request) -> dict[tuple[str, str | None, str | None], FeatureFlagEvaluation]:
    if request is None:
        return {}
    storage = getattr(request, "_feature_flag_cache", None)
    if storage is None:
        storage = {}
        request._feature_flag_cache = storage
    return storage


def resolve_workspace_id_from_request(request, view=None) -> str | None:
    """
    Best-effort workspace resolution for feature flag evaluation.

    **The returned workspace is CALLER-INFLUENCED and therefore UNTRUSTED.**
    Priority 2 below reads a ``?workspace_id=`` / ``?workspace=`` query param,
    which ranks ABOVE the authenticated user's own active workspace (4) and is
    read before any authentication has been considered. This function answers
    "which workspace is this request about?" — never "may this caller act on
    that workspace?". Callers that let the answer influence access MUST gate the
    param themselves; see ``FeatureFlagsView`` / ``FeatureFlagStatusView`` in
    ``components/shared_platform/api/controller.py``, which pair it with
    ``HasWorkspaceMembership`` for exactly this reason (ADR 0028: autosec is
    single-DB, so an unchecked workspace param IS the cross-tenant boundary).

    Composing ``RequiresFeatureFlag`` with a real auth class is what keeps an
    anonymous caller from choosing the evaluation workspace — enforced by
    ``tests/architecture/test_feature_flag_not_sole_permission.py``.

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


class _ScopeRuleSource(Protocol):
    """Anything the resolver can ask for "the rule at this scope, or None"."""

    def get(self, scope: str, default: Any = None) -> Any: ...


class _TierUnlockSource(Protocol):
    """Anything the resolver can ask "does this tier unlock this flag key?"."""

    def __contains__(self, flag_key: str) -> bool: ...


def _resolve(
    *,
    flag_key: str,
    default_enabled: bool,
    rules_by_scope: _ScopeRuleSource,
    tier_unlocked: _TierUnlockSource,
    now,
) -> FeatureFlagEvaluation:
    """THE precedence ladder — the single implementation, used by every caller.

    Resolution order:
      user -> workspace -> plan tier -> global -> ``FeatureFlag.default_enabled``

    The plan-tier layer unlocks a paid tier's feature set above the global
    default but below explicit user/workspace rules, and only ever unlocks
    (it never disables). The user-beats-workspace ordering is deliberate and
    load-bearing: ``feature.support_impersonation`` expects a per-user rule and
    is never globally enabled, and ``PROD_ALLOWLISTED_USER_FLAGS`` lets a named
    user past a global disable. Do not reorder (ADR 0020 D0).

    **Pure**: no ORM query, no cache read/write, no request. It only reads what
    it is handed. ``rules_by_scope`` is consulted in precedence order, so a
    caller may hand in a *lazy* source that fetches a scope's rule only when the
    ladder actually reaches it — which is how ``evaluate_feature_flag`` keeps its
    short-circuit while still deriving the ANSWER from this one function.
    Windowing (``starts_at``/``ends_at``) is applied here, once, for every path.
    """
    for scope, source in (
        (FeatureFlagRule.Scope.USER, "user_rule"),
        (FeatureFlagRule.Scope.WORKSPACE, "workspace_rule"),
    ):
        rule = rules_by_scope.get(scope)
        if rule is not None and rule.is_active_now(now):
            return FeatureFlagEvaluation(enabled=bool(rule.enabled), source=source)

    if flag_key in tier_unlocked:
        return FeatureFlagEvaluation(enabled=True, source="plan_tier")

    rule = rules_by_scope.get(FeatureFlagRule.Scope.GLOBAL)
    if rule is not None and rule.is_active_now(now):
        return FeatureFlagEvaluation(enabled=bool(rule.enabled), source="global_rule")

    return FeatureFlagEvaluation(enabled=bool(default_enabled), source="default")


class _LazyScopeRules:
    """Single-flag fetching strategy: one query per scope, only when reached.

    Reproduces ``evaluate_feature_flag``'s original short-circuit exactly — a
    hit at USER never queries WORKSPACE or GLOBAL — while the ANSWER comes from
    the shared ``_resolve``. The bulk path (``flags_for_context``) hands
    ``_resolve`` a plain dict instead, because it already has every rule from
    its single query.
    """

    def __init__(self, flag_id, *, user_id: str | None, workspace_id: str | None) -> None:
        self._flag_id = flag_id
        self._user_id = user_id
        self._workspace_id = workspace_id
        self._fetched: dict[str, Any] = {}

    def get(self, scope: str, default: Any = None) -> Any:
        if scope not in self._fetched:
            self._fetched[scope] = self._fetch(scope)
        rule = self._fetched[scope]
        return default if rule is None else rule

    def _fetch(self, scope: str) -> Any:
        filters: dict[str, Any] = {"flag_id": self._flag_id, "scope": scope}
        if scope == FeatureFlagRule.Scope.USER:
            if not self._user_id:
                return None
            filters["user_id"] = self._user_id
        elif scope == FeatureFlagRule.Scope.WORKSPACE:
            if not self._workspace_id:
                return None
            filters["workspace_id"] = self._workspace_id
        return FeatureFlagRule.objects.filter(**filters).only("enabled", "starts_at", "ends_at").first()


class _LazyTierUnlock:
    """Single-flag tier lookup, deferred until the ladder reaches the tier step.

    Resolving the workspace's plan costs a ``Workspace`` query; the original
    ladder only paid it when no user/workspace rule matched, so neither does
    this. ``_workspace_plan_tier`` returns ``None`` (no query) for a missing
    workspace, which ``features_for_tier`` maps to "unlocks nothing" — the same
    outcome as the original's ``if normalized_workspace_id`` guard.
    """

    def __init__(self, workspace_id: str | None, request=None) -> None:
        self._workspace_id = workspace_id
        self._request = request
        self._unlocked: frozenset[str] | None = None

    def __contains__(self, flag_key: str) -> bool:
        if self._unlocked is None:
            self._unlocked = features_for_tier(_workspace_plan_tier(self._workspace_id, self._request))
        return flag_key in self._unlocked


def evaluate_feature_flag(
    flag_key: str,
    *,
    user=None,
    workspace_id: str | None = None,
    request=None,
) -> FeatureFlagEvaluation:
    """
    Evaluate a single flag for a given user/workspace context.

    Owns the fetching (lazy, one query per scope reached) and the caching
    (per-request dict + version-keyed shared cache); the precedence decision
    itself belongs to ``_resolve``, shared with ``flags_for_context``.
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

    def _store(result: FeatureFlagEvaluation) -> FeatureFlagEvaluation:
        _cache_adapter.set_evaluation(shared_key, {"enabled": result.enabled, "source": result.source}, timeout=300)
        if per_request is not None:
            per_request[cache_key] = result
        return result

    flag = FeatureFlag.objects.filter(key=normalized_flag_key).only("id", "default_enabled").first()
    if not flag:
        return _store(FeatureFlagEvaluation(enabled=False, source="missing_flag"))

    return _store(
        _resolve(
            flag_key=normalized_flag_key,
            default_enabled=flag.default_enabled,
            rules_by_scope=_LazyScopeRules(
                flag.id,
                user_id=user_id if user else None,
                workspace_id=normalized_workspace_id,
            ),
            tier_unlocked=_LazyTierUnlock(normalized_workspace_id, request),
            now=timezone.now(),
        )
    )


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

    Intended for frontend bootstrapping; avoid calling in hot loops. Owns its own
    fetching (one query for every rule in scope) and caching; the precedence
    decision per flag belongs to ``_resolve``, shared with
    ``evaluate_feature_flag`` — the frontend bootstrap and the backend gate
    therefore cannot answer differently.
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

    # Bucket by scope. Windowing is NOT applied here — ``_resolve`` owns
    # ``starts_at``/``ends_at`` for every path, so the two paths cannot drift on
    # scheduling. (One rule per flag per scope-target is guaranteed by the
    # model's unique constraints, so a bucket never loses an active rule to an
    # inactive one.)
    global_rules = {}
    workspace_rules = {}
    user_rules = {}
    for rule in rules:
        if rule.scope == FeatureFlagRule.Scope.GLOBAL:
            global_rules[rule.flag_id] = rule
        elif (
            rule.scope == FeatureFlagRule.Scope.WORKSPACE
            and normalized_workspace_id
            and str(rule.workspace_id) == normalized_workspace_id
        ):
            workspace_rules[rule.flag_id] = rule
        elif rule.scope == FeatureFlagRule.Scope.USER and user_id and str(rule.user_id) == str(user_id):
            user_rules[rule.flag_id] = rule

    # Plan-tier unlock set for this workspace — one lookup for the whole map.
    tier_unlocked = features_for_tier(_workspace_plan_tier(normalized_workspace_id, request))

    results: dict[str, Any] = {}
    for flag in flags:
        evaluation = _resolve(
            flag_key=flag.key,
            default_enabled=flag.default_enabled,
            rules_by_scope={
                FeatureFlagRule.Scope.USER: user_rules.get(flag.id),
                FeatureFlagRule.Scope.WORKSPACE: workspace_rules.get(flag.id),
                FeatureFlagRule.Scope.GLOBAL: global_rules.get(flag.id),
            },
            tier_unlocked=tier_unlocked,
            now=now,
        )

        if include_sources:
            results[flag.key] = {"enabled": evaluation.enabled, "source": evaluation.source}
        else:
            results[flag.key] = evaluation.enabled

    _cache_adapter.set_evaluation(shared_key, results, timeout=300)
    return results
