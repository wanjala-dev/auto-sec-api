"""DeepRun checkpoint saver — id-scheme compatibility.

Legacy checkpoints were keyed by integer timestamps; langgraph 1.x keys them
by lexicographically time-ordered UUID6 strings (``checkpoint["id"]``). The
saver must read threads holding either scheme — or both at once (a thread
resumed across the upgrade). ``int(key)`` on a UUID key raised ValueError and
killed every autonomous dispatch at resume (2026-07-19).
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.deep.checkpoints import (
    DatabaseSaver,
)

# Two UUID6 ids in chronological order (time-high field increases).
_UUID_OLDER = "1f183c21-f28a-6385-bfff-9c1ce0d05555"
_UUID_NEWER = "1f183c99-0000-6385-bfff-9c1ce0d05555"


def _make_checkpoint(cp_id: str) -> dict:
    return {"id": cp_id, "channel_values": {"marker": cp_id}}


@pytest.mark.django_db(databases=["default"])
class TestCheckpointIdSchemes:
    @pytest.fixture(autouse=True)
    def _seed_runs(self, user_factory, workspace_factory):
        from infrastructure.persistence.ai.agents.models import DeepRun

        user = user_factory()
        workspace = workspace_factory(owner=user)
        for thread_id in (
            "thread-uuid",
            "thread-uuid2",
            "thread-mixed",
            "thread-legacy",
            "thread-list",
        ):
            DeepRun.objects.create(thread_id=thread_id, plan_id=thread_id, user=user, workspace=workspace)

    def _saver(self):
        return DatabaseSaver()

    def _put(self, saver, thread_id, cp_id):
        saver.put(
            {"configurable": {"thread_id": thread_id}},
            _make_checkpoint(cp_id),
            {"source": "test", "step": 0},
        )

    def test_uuid_checkpoint_roundtrips(self):
        saver = self._saver()
        self._put(saver, "thread-uuid", _UUID_OLDER)

        tup = saver.get_tuple({"configurable": {"thread_id": "thread-uuid"}})
        assert tup is not None
        assert tup.checkpoint["id"] == _UUID_OLDER

    def test_latest_wins_among_uuid_keys(self):
        saver = self._saver()
        self._put(saver, "thread-uuid2", _UUID_OLDER)
        self._put(saver, "thread-uuid2", _UUID_NEWER)

        tup = saver.get_tuple({"configurable": {"thread_id": "thread-uuid2"}})
        assert tup.checkpoint["id"] == _UUID_NEWER

    def test_mixed_legacy_and_uuid_keys_do_not_crash(self):
        """A thread spanning the upgrade holds int AND uuid keys.

        The uuid row must win (it is the newer write) and nothing may raise.
        """
        saver = self._saver()
        self._put(saver, "thread-mixed", "1721400000000")  # legacy int-timestamp key
        self._put(saver, "thread-mixed", _UUID_OLDER)

        tup = saver.get_tuple({"configurable": {"thread_id": "thread-mixed"}})
        assert tup.checkpoint["id"] == _UUID_OLDER

    def test_legacy_int_keys_still_ordered(self):
        saver = self._saver()
        self._put(saver, "thread-legacy", "100")
        self._put(saver, "thread-legacy", "200")

        tup = saver.get_tuple({"configurable": {"thread_id": "thread-legacy"}})
        assert tup.checkpoint["id"] == "200"

    def test_list_handles_uuid_keys(self):
        saver = self._saver()
        self._put(saver, "thread-list", _UUID_OLDER)
        self._put(saver, "thread-list", _UUID_NEWER)

        tuples = list(saver.list({"configurable": {"thread_id": "thread-list"}}))
        assert {t.checkpoint["id"] for t in tuples} == {_UUID_OLDER, _UUID_NEWER}
