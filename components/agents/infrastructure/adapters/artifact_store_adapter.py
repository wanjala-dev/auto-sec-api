"""ORM-backed adapter for ArtifactStorePort.

Wraps the legacy ``apps.ai.agents.deep.artifacts`` module and
DeepArtifact model behind the clean port contract.
"""
from __future__ import annotations

from infrastructure.persistence.ai.agents.models import DeepArtifact, DeepRun

from components.agents.application.ports.artifact_store_port import (
    ArtifactRecord,
    ArtifactReference,
    ArtifactStorePort,
)


def _to_serializable(value):
    """Best-effort JSON-safe conversion."""
    try:
        from components.agents.domain.services.deep.utils import to_serializable
        return to_serializable(value)
    except ImportError:
        return value


class OrmArtifactStoreAdapter(ArtifactStorePort):
    """Django ORM implementation of ArtifactStorePort."""

    def store(
        self,
        payload: dict,
        *,
        kind: str = "generic",
        metadata: dict | None = None,
        run_thread_id: str | None = None,
        task_id: str | None = None,
    ) -> ArtifactReference:
        summary = None
        if isinstance(payload, dict):
            summary = payload.get("summary") or payload.get("title")

        serializable = _to_serializable(payload)
        base_uri = f"artifact://deep-run/{run_thread_id or 'ephemeral'}"

        deep_run = (
            DeepRun.objects.filter(thread_id=run_thread_id).first()
            if run_thread_id
            else None
        )

        if deep_run:
            artifact = DeepArtifact.objects.create(
                deep_run=deep_run,
                task_id=task_id or "",
                uri="",
                summary=summary or "",
                data=(
                    serializable
                    if isinstance(serializable, dict)
                    else {"value": serializable}
                ),
                metadata={**(metadata or {}), "kind": kind},
            )
            artifact_uri = f"{base_uri}/{task_id or 'task'}/{artifact.id}"
            artifact.uri = artifact_uri
            update_fields = ["uri"]
            if hasattr(artifact, "updated_at"):
                update_fields.append("updated_at")
            artifact.save(update_fields=update_fields)
        else:
            artifact_uri = f"{base_uri}/{task_id or 'task'}/{id(payload)}"

        return ArtifactReference(
            uri=artifact_uri,
            summary=summary,
            metadata=metadata or {},
        )

    def get_by_uri(self, uri: str) -> ArtifactRecord | None:
        artifact = DeepArtifact.objects.filter(uri=uri).first()
        if not artifact:
            return None
        return self._to_record(artifact)

    def list_by_run(self, run_thread_id: str) -> list[ArtifactRecord]:
        deep_run = DeepRun.objects.filter(thread_id=run_thread_id).first()
        if not deep_run:
            return []
        artifacts = DeepArtifact.objects.filter(deep_run=deep_run).order_by("id")
        return [self._to_record(a) for a in artifacts]

    @staticmethod
    def _to_record(artifact: DeepArtifact) -> ArtifactRecord:
        return ArtifactRecord(
            id=str(artifact.id),
            uri=artifact.uri or "",
            run_id=str(artifact.deep_run_id) if artifact.deep_run_id else None,
            task_id=artifact.task_id or "",
            summary=artifact.summary or "",
            data=artifact.data if isinstance(artifact.data, dict) else {},
            metadata=artifact.metadata if isinstance(artifact.metadata, dict) else {},
        )
