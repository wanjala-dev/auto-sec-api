import pytest

from components.agents.infrastructure.gateways.deep.artifacts import store_artifact
from infrastructure.persistence.ai.agents.models import DeepRun, DeepArtifact


@pytest.mark.django_db(databases=["default"])
def test_store_artifact_persists_to_deeprun(user_factory, workspace_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    run = DeepRun.objects.create(thread_id="thread-1", plan_id="plan-1", user=user, workspace=workspace)

    ref = store_artifact(
        {"summary": "did thing", "details": {"foo": "bar"}},
        kind="task_result",
        metadata={"extra": True},
        run_thread_id=run.thread_id,
        task_id="task-123",
    )

    artifact = DeepArtifact.objects.get(deep_run=run)
    assert artifact.summary == "did thing"
    assert artifact.metadata.get("extra") is True
    assert artifact.metadata.get("kind") == "task_result"
    assert artifact.data.get("details") == {"foo": "bar"}
    assert ref.uri == artifact.uri
    assert ref.summary == "did thing"
