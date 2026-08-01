"""Data migration: copy GitHubConnection rows → VcsConnection (ADR 0010 Phase 2).

Idempotent — keyed on the source row's primary key, so a re-run is a no-op and the
identity is preserved. Deprecates GitHubConnection as a read source: the draft-PR
use case now reads VcsConnection; this seeds it from any existing (dogfood) GitHub
rows so nothing breaks. Mirrors ADR 0008's trail_s3_bucket → WorkspaceLogSource seed.
"""

from __future__ import annotations

from django.db import migrations


def copy_github_connections(apps, schema_editor):
    GitHubConnection = apps.get_model("integrations", "GitHubConnection")
    VcsConnection = apps.get_model("integrations", "VcsConnection")

    for gh in GitHubConnection.objects.all().iterator():
        _, created = VcsConnection.objects.get_or_create(
            id=gh.id,  # preserve identity → idempotent on re-run
            defaults={
                "workspace_id": gh.workspace_id,
                "provider": "github",
                "name": gh.name or "GitHub",
                "repo_allowlist": gh.repo_allowlist or [],
                "base_url": "",
                "token_ciphertext": gh.token_ciphertext or "",
                "status": gh.status,
                "last_used_at": gh.last_used_at,
                "last_error": gh.last_error or "",
                "created_by_id": gh.created_by_id,
            },
        )
        if created:
            # created_at is auto_now_add; .update() bypasses it to preserve the original.
            VcsConnection.objects.filter(id=gh.id).update(created_at=gh.created_at)


def noop_reverse(apps, schema_editor):
    # No-op reverse: dropping copied rows could lose edits made after the copy. The
    # forward copy is idempotent; leave the rows in place.
    pass


class Migration(migrations.Migration):
    dependencies = [("integrations", "0007_vcsconnection")]
    operations = [migrations.RunPython(copy_github_connections, noop_reverse)]
