"""Pin ``to_serializable`` against the 2026-05-08 datetime incident.

After PR #75 (per-task agent routing) the planner prompt started
nudging the LLM to emit ``due_date`` strings on each task. Pydantic
parsed those into real ``datetime`` objects on
``TaskSpec.due_date: Optional[datetime]``. The next downstream
``json.dumps`` — DeepRun.state JSONField persist, LangGraph
checkpoint write, or run_context push — exploded with
"Object of type datetime is not JSON serializable" and 5xx'd every
chat request.

Root cause was ``utils.to_serializable`` using ``model_dump()``
without ``mode="json"``: Pydantic v2 keeps datetime / UUID / Decimal
as live Python objects in default mode. The fix uses
``model_dump(mode="json")`` AND covers raw container values so a
dict carrying a plain ``datetime.now()`` (e.g. run_context with a
timestamp) also serialises cleanly.
"""
from __future__ import annotations

import json
from datetime import datetime, date, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from components.agents.domain.services.deep.utils import to_serializable


class TestPydanticModelWithDatetimeField:
    """The exact prod incident shape — TaskSpec carries an
    ``Optional[datetime]`` and the LLM populates it.
    """

    def test_taskspec_with_due_date_serialises_to_json(self):
        from components.agents.domain.value_objects.plan_schemas import TaskSpec

        task = TaskSpec(
            title="ship the deploy",
            due_date=datetime(2026, 5, 8, 21, 30, 0, tzinfo=timezone.utc),
        )
        result = to_serializable(task)
        # Should round-trip through json.dumps without raising.
        encoded = json.dumps(result)
        assert "2026-05-08" in encoded, (
            "TaskSpec.due_date must serialise to an ISO string, not a "
            "live datetime object — this was the 2026-05-08 incident."
        )

    def test_planspec_with_tasks_carrying_due_dates_round_trips(self):
        """Mirrors what LangGraph state and DeepRun.state actually
        stored in prod when the bug fired.
        """
        from components.agents.domain.value_objects.plan_schemas import (
            PlanSpec,
            TaskSpec,
        )

        plan = PlanSpec(
            plan_id="p-1",
            goal="anything",
            tasks=[
                TaskSpec(
                    title="task with date",
                    due_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
                    agent_type="budget_agent",
                ),
                TaskSpec(title="task without date"),
            ],
        )
        # No explicit assertion needed — if json.dumps raises, the
        # fix has regressed.
        json.dumps(to_serializable(plan))


class TestRawDatetimeInDict:
    """run_context, telemetry payloads, and other plain dicts that
    haven't passed through a Pydantic model. Pre-fix these would
    blow up too if anyone slipped a ``timezone.now()`` in.
    """

    def test_dict_with_raw_datetime_serialises(self):
        payload = {
            "run_id": "r-1",
            "started_at": datetime(2026, 5, 8, 21, 30, tzinfo=timezone.utc),
        }
        result = to_serializable(payload)
        encoded = json.dumps(result)
        assert "2026-05-08" in encoded
        assert result["started_at"].startswith("2026-05-08")

    def test_dict_with_date_uuid_decimal_all_round_trip(self):
        payload = {
            "as_of": date(2026, 5, 8),
            "user_id": UUID("12b614c1-1706-4cbc-b9df-14875dd3551d"),
            "amount": Decimal("123.45"),
        }
        encoded = json.dumps(to_serializable(payload))
        assert "2026-05-08" in encoded
        assert "12b614c1-1706-4cbc-b9df-14875dd3551d" in encoded
        assert "123.45" in encoded


class TestNestedContainers:
    def test_list_of_models_each_serialise(self):
        from components.agents.domain.value_objects.plan_schemas import TaskSpec

        tasks = [
            TaskSpec(title="t1", due_date=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            TaskSpec(title="t2", due_date=datetime(2026, 2, 1, tzinfo=timezone.utc)),
        ]
        json.dumps(to_serializable(tasks))

    def test_dict_of_lists_of_dicts_with_datetimes(self):
        payload = {
            "events": [
                {"ts": datetime(2026, 5, 8, 21, 30, tzinfo=timezone.utc), "type": "x"},
                {"ts": datetime(2026, 5, 8, 21, 31, tzinfo=timezone.utc), "type": "y"},
            ],
        }
        json.dumps(to_serializable(payload))


class TestPrimitivesUnchanged:
    """Sanity — primitives that were already JSON-safe must not be
    transformed. If we ever get clever and do ``str(value)`` on a
    fall-through, ints become strings and downstream readers break.
    """

    @pytest.mark.parametrize(
        "value",
        [None, "string", 42, 3.14, True, False],
    )
    def test_primitive_is_returned_unchanged(self, value):
        assert to_serializable(value) == value
        assert type(to_serializable(value)) is type(value)
