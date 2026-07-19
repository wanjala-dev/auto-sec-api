"""
Artifact storage layer for deep agents.

Persists artifact metadata + payload on DeepArtifact rows and returns lightweight
references suitable for prompts. Payloads are JSON-serialised into the `data`
column; URIs use a predictable scheme so callers can render/download later.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from components.agents.domain.value_objects.plan_schemas import ArtifactRef
from components.agents.domain.services.deep.utils import to_serializable


def store_artifact(
    payload: Dict,
    *,
    kind: str = "generic",
    metadata: Optional[Dict] = None,
    run_thread_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> ArtifactRef:
    """
    Persist an artifact and return a reference.

    Payload is JSON-serialised into DeepArtifact.data for quick retrieval. When
    a DeepRun exists for the thread_id, the artifact is linked; otherwise this
    still returns a reference-only URI.
    """
    from infrastructure.persistence.ai.agents.models import DeepRun, DeepArtifact

    summary = None
    if isinstance(payload, dict):
        summary = payload.get("summary") or payload.get("title")
    serializable_payload: Any = to_serializable(payload)
    base_uri = f"artifact://deep-run/{run_thread_id or 'ephemeral'}"

    artifact_uri = f"{base_uri}/{task_id or 'task'}/{id(payload)}"
    deep_run = DeepRun.objects.filter(thread_id=run_thread_id).first() if run_thread_id else None
    if deep_run:
        artifact = DeepArtifact.objects.create(
            deep_run=deep_run,
            task_id=task_id or "",
            uri="",  # populated below for deterministic pk-based URI
            summary=summary or "",
            data=serializable_payload if isinstance(serializable_payload, dict) else {"value": serializable_payload},
            metadata={**(metadata or {}), "kind": kind},
        )
        artifact_uri = f"{base_uri}/{task_id or 'task'}/{artifact.id}"
        artifact.uri = artifact_uri
        artifact.save(update_fields=["uri", "updated_at"] if hasattr(artifact, "updated_at") else ["uri"])

    ref = ArtifactRef(uri=artifact_uri, summary=summary, metadata=metadata or {})
    return ref
