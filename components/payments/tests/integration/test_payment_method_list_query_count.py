"""N+1 regression guards for the payment-method list endpoints.

Two serializers render a per-method ``plans`` block:

* ``GET /workspaces/payments/workspaces/<ws>/methods/`` →
  ``WorkspacePaymentMethodSerializer.get_plans`` +
  ``PaymentPlanSerializer.recipient_name`` (reads ``plan.recipient``).
* ``GET /workspaces/payments/public/workspaces/<ws>/`` (the public donate form) →
  ``PublicPaymentMethodSerializer.get_plans`` (used to fire a plans query, an
  ``exists()`` probe AND a re-filter per method row).

Before the fix each method row fired its own plans query and each plan its
own recipient query. The controllers now ``Prefetch`` the exact
filtered/ordered plan sets (with ``select_related("recipient")``) so the
query count must be constant w.r.t. the number of plans/methods.
"""
from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

pytestmark = [pytest.mark.django_db]


def _query_count(api_client, url: str) -> int:
    with CaptureQueriesContext(connection) as ctx:
        res = api_client.get(url)
        assert res.status_code == 200, res.content
    return len(ctx.captured_queries)


def test_workspace_method_list_query_count_is_constant(
    api_client,
    user_factory,
    workspace_factory,
    recipient_factory,
    payment_method_factory,
    payment_plan_factory,
):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    api_client.force_authenticate(user=owner)
    method = payment_method_factory(workspace)
    url = f"/workspaces/payments/workspaces/{workspace.id}/methods/"

    for idx in range(2):
        recipient = recipient_factory(workspace=workspace)
        payment_plan_factory(
            method, context="recipient_sponsorship", slug=f"plan-{idx}", recipient=recipient
        )
    _query_count(api_client, url)  # warm up one-time caches
    baseline = _query_count(api_client, url)

    # More plans (each with its own recipient) must NOT grow the query count;
    # the old per-plan ``obj.recipient`` read added one query per plan.
    for idx in range(2, 6):
        recipient = recipient_factory(workspace=workspace)
        payment_plan_factory(
            method, context="recipient_sponsorship", slug=f"plan-{idx}", recipient=recipient
        )
    grown = _query_count(api_client, url)

    assert grown == baseline, (
        f"Payment-method plans N+1 regression: {baseline} queries with 2 "
        f"plans but {grown} with 6 — the count must be constant w.r.t. plan count."
    )


def _make_public_method(workspace, payment_method_factory, payment_plan_factory, idx: int):
    """One publicly-listable method per distinct MANUAL provider.

    A workspace can hold only one method per provider (unique constraint), so
    growing the method count requires a provider per method.
    """
    from django.apps import apps as django_apps

    PaymentProvider = django_apps.get_model("workspaces", "PaymentProvider")
    provider = PaymentProvider.objects.create(
        slug=f"manual-qc-{idx}",
        display_name=f"Manual QC {idx}",
        provider_type="manual",
        capabilities=["donations"],
    )
    method = payment_method_factory(workspace, provider=provider)
    method.allow_public_listing = True
    method.save(update_fields=["allow_public_listing"])
    payment_plan_factory(method, context="donations", slug=f"pub-plan-{idx}")
    return method


def _public_serialize_query_count(workspace) -> int:
    """Serialize the public methods the way the view does.

    Mirrors ``PublicWorkspacePaymentMethodView.get`` — same Prefetch into
    ``prefetched_context_plans``, same serializer context — minus the JSONB
    ``enabled_contexts__contains`` filter, which the SQLite test backend does
    not support (pre-existing; production runs PostgreSQL where it works).
    The N+1 being guarded lives in the Prefetch + ``get_plans`` pair, which
    this exercises exactly.
    """
    from django.apps import apps as django_apps
    from django.db.models import Prefetch

    from components.payments.mappers.rest.payment_serializers import (
        PublicPaymentMethodSerializer,
    )

    WorkspacePaymentMethod = django_apps.get_model("workspaces", "WorkspacePaymentMethod")
    PaymentPlan = django_apps.get_model("workspaces", "PaymentPlan")
    methods = (
        WorkspacePaymentMethod.objects.filter(workspace=workspace, is_deleted=False)
        .select_related("provider")
        .prefetch_related(
            Prefetch(
                "plans",
                queryset=PaymentPlan.objects.filter(context="donations", is_active=True)
                .select_related("recipient")
                .order_by("sort_order", "created_at"),
                to_attr="prefetched_context_plans",
            )
        )
        .order_by("sort_order", "created_at")
    )
    with CaptureQueriesContext(connection) as ctx:
        _ = PublicPaymentMethodSerializer(
            methods,
            many=True,
            context={"plan_filters": {"context": "donations", "recipient_id": None}},
        ).data
    return len(ctx.captured_queries)


def test_public_method_list_query_count_is_constant(
    user_factory,
    workspace_factory,
    payment_method_factory,
    payment_plan_factory,
):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)

    for idx in range(2):
        _make_public_method(workspace, payment_method_factory, payment_plan_factory, idx)
    baseline = _public_serialize_query_count(workspace)

    # More methods must NOT grow the query count; each method used to fire a
    # plans query (plus exists + re-filter when a recipient_id is supplied).
    for idx in range(2, 5):
        _make_public_method(workspace, payment_method_factory, payment_plan_factory, idx)
    grown = _public_serialize_query_count(workspace)

    assert grown == baseline, (
        f"Public payment-method N+1 regression: {baseline} queries with 2 "
        f"methods but {grown} with 5 — the count must be constant w.r.t. method count."
    )
