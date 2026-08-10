"""Column widths must actually hold what every producer emits.

A width mismatch in this context is not a storage bug, it is an attribution bug:
``origin_id``, ``ProvenanceActor.external_ref`` and ``ProvenanceResource.external_ref``
each back a ``UniqueConstraint``, so a value that does not fit either explodes at
insert (PostgreSQL) or, if some producer trims it to fit first, merges two
distinct rows (everywhere). These tests are the cheap standing guard that the
domain's declared limits and the columns behind them never drift apart, and that
the enum-backed columns still fit their own choices.

No database is touched — this is model metadata only.
"""

from __future__ import annotations

import pytest

from components.provenance.domain.entities.agent_activity_entity import (
    MAX_ACTION_LENGTH,
    MAX_AGENT_URN_LENGTH,
    MAX_ORIGIN_ID_LENGTH,
    MAX_RESOURCE_REF_LENGTH,
)
from components.provenance.domain.value_objects.agent_urn import MAX_URN_LENGTH
from infrastructure.persistence.provenance.models import (
    ActorType,
    AgentTelemetrySource,
    PermissionLevel,
    ProvenanceActor,
    ProvenanceEvent,
    ProvenanceResource,
    SourceSystem,
)

pytestmark = pytest.mark.integration


def _width(model, field_name: str) -> int:
    return model._meta.get_field(field_name).max_length


@pytest.mark.parametrize(
    ("model", "field_name", "declared_limit"),
    [
        (ProvenanceEvent, "origin_id", MAX_ORIGIN_ID_LENGTH),
        (ProvenanceEvent, "action", MAX_ACTION_LENGTH),
        (ProvenanceActor, "external_ref", MAX_AGENT_URN_LENGTH),
        (ProvenanceActor, "external_ref", MAX_URN_LENGTH),
        (ProvenanceResource, "external_ref", MAX_RESOURCE_REF_LENGTH),
    ],
)
def test_domain_limit_matches_its_column(model, field_name, declared_limit):
    assert _width(model, field_name) == declared_limit


def test_origin_id_holds_every_key_shape_we_produce():
    """The four live producers, longest realistic value each.

    audit backfill ``str(EntityAuditLog.id)``; AI backfill ``<task_uuid>:<index>``;
    agent telemetry ``<trace>:<span>`` for W3C trace context, AWS X-Ray, and a
    UUID-keyed runtime.
    """
    longest_per_producer = {
        "audit_log": 36,  # a UUID
        "ai_action": 36 + 1 + 10,  # <task_uuid>:<index>
        "agent_runtime_w3c": 32 + 1 + 16,
        "agent_runtime_xray": 35 + 1 + 16,
        "agent_runtime_uuid_keyed": 36 + 1 + 36,
    }

    widest = max(longest_per_producer.values())

    assert widest <= _width(ProvenanceEvent, "origin_id")
    # …and the domain refuses anything the column could not hold.
    assert _width(ProvenanceEvent, "origin_id") == MAX_ORIGIN_ID_LENGTH


@pytest.mark.parametrize(
    ("model", "field_name", "choices"),
    [
        (ProvenanceEvent, "origin", ProvenanceEvent.Origin),
        (ProvenanceEvent, "source_system", SourceSystem),
        (ProvenanceActor, "source_system", SourceSystem),
        (ProvenanceActor, "actor_type", ActorType),
        (ProvenanceResource, "source_system", SourceSystem),
        (AgentTelemetrySource, "kind", AgentTelemetrySource.Kind),
        (AgentTelemetrySource, "status", AgentTelemetrySource.Status),
    ],
)
def test_enum_backed_column_fits_all_of_its_choices(model, field_name, choices):
    """Enum-backed widths were assumed safe in review; assume nothing — and keep
    them safe when someone adds a longer member."""
    longest = max(len(value) for value in choices.values)

    assert longest <= _width(model, field_name)


def test_permission_levels_fit_wherever_they_are_rendered():
    """``AccessGrant.permissions`` is JSON, so the only width risk is a future
    move to a CharField. Pin the longest value so that move is a conscious one."""
    assert max(len(value) for value in PermissionLevel.values) <= 24
