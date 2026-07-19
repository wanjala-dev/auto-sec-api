"""Index SOC findings (triage-board tasks) into the workspace knowledge corpus.

Makes the workspace's real findings retrievable by the writing agent's RAG
grounding, so AI-drafted reports cite actual triage data instead of drafting
from the prompt alone. Idempotent: each finding indexes under a stable
``finding:<workspace>:<task>`` document key (re-runs upsert, not duplicate).

Usage:
    python manage.py index_findings_rag --workspace <uuid>
    python manage.py index_findings_rag            # all workspaces with tasks
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Index SOC findings (project tasks) into the workspace RAG corpus."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", help="Workspace UUID (default: all)")

    def handle(self, *args, **options):
        from components.knowledge.application.providers.knowledge_text_ingest_provider import (
            KnowledgeTextIngestProvider,
        )
        from infrastructure.persistence.project.models import Task

        qs = Task.objects.select_related("column", "team", "project").order_by("created_at")
        if options.get("workspace"):
            qs = qs.filter(workspace_id=options["workspace"])

        port = KnowledgeTextIngestProvider().build_port()
        indexed = 0
        for task in qs.iterator(chunk_size=500):
            parts = [f"Security finding: {task.title}"]
            if task.description:
                parts.append(task.description)
            parts.append(f"Status/lane: {getattr(task.column, 'title', task.status)}")
            parts.append(f"Team: {getattr(task.team, 'title', '')}")
            if task.project:
                parts.append(f"Project: {task.project.title}")
            if task.priority:
                parts.append(f"Priority: {task.priority}")
            if task.source_type:
                parts.append(f"Source: {task.source_type}")
            if task.metadata:
                parts.append(f"Context: {task.metadata}")
            corpus = "\n".join(p for p in parts if p and str(p).strip())
            try:
                port.index_text(
                    text=corpus,
                    document_key=f"finding:{task.workspace_id}:{task.id}",
                    metadata={
                        "source": "finding",
                        "workspace_id": str(task.workspace_id),
                        "task_id": str(task.id),
                        "title": task.title or "",
                        "status": "active",
                        "privacy": "private",
                    },
                )
                indexed += 1
            except Exception:
                self.stderr.write(f"failed to index task {task.id}")

        self.stdout.write(self.style.SUCCESS(f"indexed {indexed} findings into the RAG corpus"))
