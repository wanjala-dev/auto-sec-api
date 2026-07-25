"""ProvenanceResource carries the canonical asset_urn (ADR 0004 Phase 2).

The graph node is now keyed by the same cross-pillar identity a finding will use to
correlate to it. The pre_save bridge stamps it on every write path, so no ingester
has to remember to.
"""

from __future__ import annotations

import uuid

import pytest

from infrastructure.persistence.provenance.models import ProvenanceResource

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _make(ws, *, source_system: str, external_ref: str, asset_urn: str = "") -> ProvenanceResource:
    return ProvenanceResource.objects.create(
        workspace=ws,
        resource_type="bucket",
        source_system=source_system,
        external_ref=external_ref,
        asset_urn=asset_urn,
    )


def test_aws_arn_is_used_verbatim_as_urn(workspace_factory):
    ws = workspace_factory()
    resource = _make(ws, source_system="aws", external_ref="arn:aws:s3:::my-bucket")
    resource.refresh_from_db()
    assert resource.asset_urn == "arn:aws:s3:::my-bucket"


def test_opaque_ref_is_namespaced_by_source(workspace_factory):
    ws = workspace_factory()
    resource = _make(ws, source_system="internal", external_ref=str(uuid.uuid4()))
    resource.refresh_from_db()
    assert resource.asset_urn == f"urn:internal:{resource.external_ref}"


def test_explicit_asset_urn_is_preserved(workspace_factory):
    ws = workspace_factory()
    resource = _make(ws, source_system="aws", external_ref="arn:aws:s3:::b", asset_urn="urn:custom:override")
    resource.refresh_from_db()
    assert resource.asset_urn == "urn:custom:override"


def test_urn_is_stable_across_resaves(workspace_factory):
    ws = workspace_factory()
    resource = _make(ws, source_system="aws", external_ref="arn:aws:iam::1:role/x")
    resource.refresh_from_db()
    first = resource.asset_urn
    resource.display_name = "renamed"
    resource.save()
    resource.refresh_from_db()
    assert resource.asset_urn == first == "arn:aws:iam::1:role/x"
