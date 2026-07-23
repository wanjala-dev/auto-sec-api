import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

_ACTOR_TYPE_CHOICES = [
    ("human", "Human"),
    ("service_account", "Service account"),
    ("ai_agent", "AI agent"),
    ("vendor_integration", "Vendor / integration"),
]

_SOURCE_SYSTEM_CHOICES = [
    ("internal", "autosec internal (audit trail)"),
    ("ai", "autosec AI agents"),
    ("identity", "autosec identity (sessions / roles)"),
    ("aws", "AWS (IAM / CloudTrail)"),
    ("okta", "Okta"),
    ("google_workspace", "Google Workspace"),
    ("slack", "Slack"),
    ("github", "GitHub"),
]

_ORIGIN_CHOICES = [
    ("audit_log", "EntityAuditLog"),
    ("ai_action", "AI action"),
    ("identity_session", "Identity session"),
    ("vendor_log", "Vendor audit log"),
]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("workspaces", "0004_workspace_domains"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProvenanceActor",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("actor_type", models.CharField(choices=_ACTOR_TYPE_CHOICES, max_length=24)),
                ("source_system", models.CharField(choices=_SOURCE_SYSTEM_CHOICES, max_length=24)),
                ("external_ref", models.CharField(max_length=255)),
                ("display_name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "agent_ref",
                    models.UUIDField(blank=True, help_text="Agent.agent_id for ai_agent actors.", null=True),
                ),
                ("integration_ref", models.CharField(blank=True, default="", max_length=64)),
                ("is_active", models.BooleanField(default=True)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="provenance_actors",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="provenance_actors",
                        to="workspaces.workspace",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ProvenanceResource",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("resource_type", models.CharField(max_length=64)),
                ("source_system", models.CharField(choices=_SOURCE_SYSTEM_CHOICES, max_length=24)),
                ("external_ref", models.CharField(max_length=512)),
                ("display_name", models.CharField(blank=True, default="", max_length=255)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="provenance_resources",
                        to="workspaces.workspace",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="AccessGrant",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("permissions", models.JSONField(default=list, help_text="List of PermissionLevel values.")),
                ("scope", models.CharField(blank=True, default="", max_length=255)),
                (
                    "source",
                    models.CharField(blank=True, default="", help_text="What conferred the grant.", max_length=255),
                ),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grants",
                        to="provenance.provenanceactor",
                    ),
                ),
                (
                    "resource",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grants",
                        to="provenance.provenanceresource",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="provenance_grants",
                        to="workspaces.workspace",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ProvenanceEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(max_length=128)),
                ("occurred_at", models.DateTimeField()),
                ("source_system", models.CharField(choices=_SOURCE_SYSTEM_CHOICES, max_length=24)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("origin", models.CharField(choices=_ORIGIN_CHOICES, max_length=24)),
                ("origin_id", models.CharField(max_length=64)),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="provenance.provenanceactor",
                    ),
                ),
                (
                    "resource",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="provenance.provenanceresource",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="provenance_events",
                        to="workspaces.workspace",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="provenanceactor",
            constraint=models.UniqueConstraint(
                fields=("workspace", "source_system", "external_ref"),
                name="uniq_provenance_actor_identity",
            ),
        ),
        migrations.AddIndex(
            model_name="provenanceactor",
            index=models.Index(fields=["workspace", "actor_type"], name="prov_actor_ws_type_idx"),
        ),
        migrations.AddIndex(
            model_name="provenanceactor",
            index=models.Index(fields=["workspace", "source_system"], name="prov_actor_ws_src_idx"),
        ),
        migrations.AddConstraint(
            model_name="provenanceresource",
            constraint=models.UniqueConstraint(
                fields=("workspace", "source_system", "external_ref"),
                name="uniq_provenance_resource_identity",
            ),
        ),
        migrations.AddIndex(
            model_name="provenanceresource",
            index=models.Index(fields=["workspace", "resource_type"], name="prov_res_ws_type_idx"),
        ),
        migrations.AddIndex(
            model_name="provenanceresource",
            index=models.Index(fields=["workspace", "source_system"], name="prov_res_ws_src_idx"),
        ),
        migrations.AddConstraint(
            model_name="accessgrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(("revoked_at__isnull", True)),
                fields=("workspace", "actor", "resource", "scope"),
                name="uniq_active_grant_per_actor_resource_scope",
            ),
        ),
        migrations.AddIndex(
            model_name="accessgrant",
            index=models.Index(fields=["workspace", "actor"], name="prov_grant_ws_actor_idx"),
        ),
        migrations.AddIndex(
            model_name="accessgrant",
            index=models.Index(fields=["workspace", "resource"], name="prov_grant_ws_res_idx"),
        ),
        migrations.AddIndex(
            model_name="accessgrant",
            index=models.Index(fields=["workspace", "revoked_at"], name="prov_grant_ws_revoked_idx"),
        ),
        migrations.AddConstraint(
            model_name="provenanceevent",
            constraint=models.UniqueConstraint(
                fields=("workspace", "origin", "origin_id"),
                name="uniq_provenance_event_projection",
            ),
        ),
        migrations.AddIndex(
            model_name="provenanceevent",
            index=models.Index(fields=["workspace", "actor", "occurred_at"], name="prov_evt_ws_actor_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="provenanceevent",
            index=models.Index(fields=["workspace", "resource", "occurred_at"], name="prov_evt_ws_res_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="provenanceevent",
            index=models.Index(fields=["workspace", "occurred_at"], name="prov_evt_ws_ts_idx"),
        ),
    ]
