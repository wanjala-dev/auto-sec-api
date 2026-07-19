"""
Checkpointer utilities for deep-agent runs.

Implements a Django DB-backed saver so LangGraph can resume runs by
thread_id/thread_ts.  Checkpoint and metadata payloads are stored as
base64-encoded serde bytes in the DeepRun.checkpoints JSON field.

Compatible with both langgraph-checkpoint 1.x (put(config, checkpoint, metadata))
and 2.x (put(config, checkpoint, metadata, new_versions)) APIs.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import AsyncIterator, Iterator, Sequence
from functools import partial
from typing import Any

from langchain_core.runnables.config import RunnableConfig

logger = logging.getLogger(__name__)

# Import checkpoint types — handle both old (langgraph.checkpoint.base)
# and new (langgraph_checkpoint) package locations.
try:
    from langgraph.checkpoint.base import (
        BaseCheckpointSaver,
        Checkpoint,
        CheckpointMetadata,
        CheckpointTuple,
    )
except ImportError:
    from langgraph_checkpoint.base import (
        BaseCheckpointSaver,
        Checkpoint,
        CheckpointMetadata,
        CheckpointTuple,
    )

try:
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:
    from langgraph_checkpoint.memory import MemorySaver


def _encode(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _decode(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


class DatabaseSaver(BaseCheckpointSaver):
    """
    Durable LangGraph checkpointer backed by the DeepRun.checkpoints JSON field.

    Checkpoints are stored as base64-encoded serde bytes keyed by thread_ts.
    Compatible with langgraph 0.0.69 through 0.2.x+ checkpoint APIs.
    """

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        from infrastructure.persistence.ai.agents.models import DeepRun

        thread_id = config["configurable"]["thread_id"]
        thread_ts = config["configurable"].get("thread_ts")
        run = DeepRun.objects.filter(thread_id=thread_id).first()
        if not run:
            return None

        checkpoints = run.checkpoints or {}
        if thread_ts:
            saved = checkpoints.get(str(thread_ts))
            if not saved:
                return None
            return self._build_tuple(config, thread_ts, saved)

        if not checkpoints:
            return None
        latest_ts = max(checkpoints.keys(), key=lambda k: int(k))
        return self._build_tuple(
            {"configurable": {"thread_id": thread_id, "thread_ts": latest_ts}},
            latest_ts,
            checkpoints[latest_ts],
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        from infrastructure.persistence.ai.agents.models import DeepRun

        thread_ids = (
            (config["configurable"]["thread_id"],) if config else DeepRun.objects.values_list("thread_id", flat=True)
        )
        for thread_id in thread_ids:
            run = DeepRun.objects.filter(thread_id=thread_id).first()
            if not run or not run.checkpoints:
                continue
            for ts_str, saved in run.checkpoints.items():
                ts_int = int(ts_str)
                if before and ts_int >= int(before["configurable"]["thread_ts"]):
                    continue
                if limit is not None and limit <= 0:
                    break
                if filter:
                    metadata = self.serde.loads(_decode(saved["metadata"]))
                    if not all(metadata.get(k) == v for k, v in filter.items()):
                        continue
                yield self._build_tuple(
                    {"configurable": {"thread_id": thread_id, "thread_ts": ts_int}},
                    ts_int,
                    saved,
                )
                if limit is not None:
                    limit -= 1

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any | None = None,
    ) -> RunnableConfig:
        """Store a checkpoint.

        The ``new_versions`` parameter was added in langgraph-checkpoint 2.x.
        We accept it for forward compatibility but do not use it (our
        serialization format stores the full checkpoint blob).
        """
        from infrastructure.persistence.ai.agents.models import DeepRun

        thread_id = config["configurable"]["thread_id"]
        thread_ts = checkpoint["id"]
        cp_bytes = self.serde.dumps(checkpoint)
        md_bytes = self.serde.dumps(metadata)
        run, _ = DeepRun.objects.get_or_create(
            thread_id=thread_id,
            defaults={
                "plan_id": config["configurable"].get("plan_id", thread_id),
                "user_id": config["configurable"].get("user_id"),
                "workspace_id": config["configurable"].get("workspace_id"),
            },
        )
        checkpoints = run.checkpoints or {}
        checkpoints[str(thread_ts)] = {
            "checkpoint": _encode(cp_bytes),
            "metadata": _encode(md_bytes),
        }
        DeepRun.objects.filter(id=run.id).update(checkpoints=checkpoints)

        return {
            "configurable": {
                "thread_id": thread_id,
                "thread_ts": thread_ts,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Store intermediate writes for a checkpoint (langgraph-checkpoint 2.x).

        For our JSON-blob storage strategy we persist writes as part of the
        next full checkpoint via ``put()``, so this is intentionally a no-op.
        """

    # ── Async wrappers ────────────────────────────────────────────────

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_tuple, config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        loop = asyncio.get_running_loop()
        iterator = await loop.run_in_executor(
            None, partial(self.list, filter=filter, before=before, limit=limit), config
        )
        while True:
            item = await loop.run_in_executor(None, next, iterator, None)
            if item is None:
                break
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any | None = None,
    ) -> RunnableConfig:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Async version of put_writes — also a no-op."""

    # ── Internal ──────────────────────────────────────────────────────

    def _build_tuple(self, config: RunnableConfig, ts: Any, saved: dict[str, str]) -> CheckpointTuple:
        checkpoint = self.serde.loads(_decode(saved["checkpoint"]))
        metadata = self.serde.loads(_decode(saved["metadata"]))
        tuple_kwargs = {
            "config": {"configurable": {"thread_id": config["configurable"]["thread_id"], "thread_ts": int(ts)}},
            "checkpoint": checkpoint,
            "metadata": metadata,
        }
        # langgraph-checkpoint 2.x adds parent_config to CheckpointTuple
        _fields = getattr(CheckpointTuple, "_fields", None) or [f.name for f in getattr(CheckpointTuple, "__dataclass_fields__", {}).values()]
        if "parent_config" in str(_fields):
            tuple_kwargs["parent_config"] = None
        return CheckpointTuple(**tuple_kwargs)


def default_checkpointer():
    """
    Choose a durable saver for runtime; fall back to MemorySaver only on hard failure.
    """
    try:
        return DatabaseSaver()
    except Exception:
        logger.warning("DatabaseSaver failed to initialize, falling back to MemorySaver", exc_info=True)
        return MemorySaver()
