import pytest

from components.agents.infrastructure.adapters.langchain.deep.checkpoints import DatabaseSaver


@pytest.mark.django_db(databases=["default"])
def test_database_saver_persists_and_reads_checkpoints(user_factory, workspace_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    saver = DatabaseSaver()
    config = {"configurable": {"thread_id": "thread-test", "plan_id": "plan-1", "user_id": user.id, "workspace_id": workspace.id}}
    checkpoint = {"id": 1, "channel_values": {}, "versions_seen": {}}
    metadata = {"foo": "bar"}

    returned_config = saver.put(config, checkpoint, metadata)

    assert returned_config["configurable"]["thread_ts"] == 1
    retrieved = saver.get_tuple({"configurable": {"thread_id": "thread-test"}})
    assert retrieved is not None
    assert retrieved.checkpoint["id"] == 1
    assert retrieved.metadata == metadata
