"""Widen ``ProvenanceEvent.origin_id`` 64 → 128.

``origin_id`` is the idempotency key of the provenance ledger
(``UniqueConstraint(workspace, origin, origin_id)``), so its width is a
correctness property. At 64 it was already too narrow for a plausible producer:
a runtime keying spans with UUIDs emits ``<uuid>:<uuid>`` = 73 chars, and the
agent-telemetry writer truncated to fit — which does not shorten a key, it makes
two genuinely distinct agent actions collide into one event and silently
corrupts attribution.

128 holds every producer we have with headroom (audit-row UUID 36,
``<ai_task_uuid>:<index>`` ~40, W3C trace context 49, AWS X-Ray 52, UUID:UUID
73). Widening alone is not the fix, though — it only moves the cliff — so the
producer now refuses an over-length key instead of truncating it
(``AgentActivityRecord``).

Widening a varchar is a metadata-only change in PostgreSQL (no table rewrite, no
index rebuild) and every existing value stays valid, so this is safe to apply
online.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("provenance", "0003_agent_telemetry_source"),
    ]

    operations = [
        migrations.AlterField(
            model_name="provenanceevent",
            name="origin_id",
            field=models.CharField(max_length=128),
        ),
    ]
