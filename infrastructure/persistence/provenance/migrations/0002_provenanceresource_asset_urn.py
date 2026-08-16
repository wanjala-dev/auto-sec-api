"""Add the canonical ``asset_urn`` to ProvenanceResource + backfill (ADR 0004 Phase 2).

The URN canonicalisation is inlined here (not imported from
``shared_kernel.domain.security``) so this historical migration reproduces its
behaviour even if ``AssetUrn.canonical`` later changes — standard migration hygiene.
"""

from __future__ import annotations

from django.db import migrations, models


def _canonical_urn(source_system: str, external_ref: str) -> str:
    ref = (external_ref or "").strip()
    if not ref:
        return ""
    lowered = ref.lower()
    if lowered.startswith("arn:") or lowered.startswith("urn:"):
        return ref
    src = (source_system or "").strip().lower() or "unknown"
    return f"urn:{src}:{ref}"


def backfill_asset_urn(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    ProvenanceResource = apps.get_model("provenance", "ProvenanceResource")
    rows = ProvenanceResource.objects.using(db_alias).all().only("id", "source_system", "external_ref", "asset_urn")
    for resource in rows.iterator(chunk_size=500):
        if resource.asset_urn:
            continue
        urn = _canonical_urn(resource.source_system, resource.external_ref)
        if not urn:
            continue
        resource.asset_urn = urn
        resource.save(update_fields=["asset_urn"])


class Migration(migrations.Migration):
    dependencies = [
        ("provenance", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="provenanceresource",
            name="asset_urn",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AddIndex(
            model_name="provenanceresource",
            index=models.Index(fields=["workspace", "asset_urn"], name="prov_res_ws_urn_idx"),
        ),
        migrations.RunPython(backfill_asset_urn, migrations.RunPython.noop),
    ]
