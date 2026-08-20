"""A run must record WHICH prompt version produced it (ADR 0032 D1).

The unit of measurement is the configuration tuple
``(agent_type, prompt_version, model)``. Before this, ``DeepRunLog`` carried
``agent_type`` and ``model_used`` and the raw prompt TEXT — so the only way to
tell two runs on different prompt versions apart was to diff stored blobs, and
in practice every regression got attributed to the model by default. A grep for
``prompt_version`` outside tests returned nothing at all.

These tests pin the stamp at the two places rows are actually written: the
planner's ``llm_call`` row and a specialist's ``tool_observation`` row. They
also pin the fail-safe — an unregistered prompt leaves the row UNATTRIBUTED
rather than guessing a version, because a wrong attribution is worse than a
blank one.
"""

from __future__ import annotations

import uuid

import pytest

from components.agents.infrastructure.prompts.stamp import (
    prompt_stamp,
    specialist_prompt_id,
    specialist_prompt_stamp,
)
from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog

pytestmark = pytest.mark.django_db


def _run(user_factory, workspace_factory):
    workspace = workspace_factory()
    return DeepRun.objects.create(
        thread_id=str(uuid.uuid4()),
        plan_id=str(uuid.uuid4()),
        user=workspace.workspace_owner,
        workspace=workspace,
        status=DeepRun.STATUS_COMPLETED,
        state={},
    )


class TestTheStampResolver:
    def test_the_planner_prompt_resolves_to_a_real_version(self):
        prompt_id, version = prompt_stamp("planner.system")
        assert prompt_id == "planner.system"
        assert version.startswith("v")

    def test_an_unregistered_prompt_is_unattributed_not_guessed(self):
        assert prompt_stamp("no.such.prompt") == ("", "")

    def test_a_specialist_id_follows_the_registry_convention(self):
        assert specialist_prompt_id("code_security_agent") == "code_security_agent.system"

    def test_an_agent_with_no_slug_stamps_nothing(self):
        assert specialist_prompt_stamp(None) == ("", "")
        assert specialist_prompt_stamp("") == ("", "")


class TestThePlannerRowCarriesTheTuple:
    def test_an_llm_call_row_records_the_prompt_version_it_used(self, user_factory, workspace_factory):
        from components.agents.infrastructure.adapters.langchain.deep import llm_planner

        run = _run(user_factory, workspace_factory)
        prompt_id, version = prompt_stamp(llm_planner.PLANNER_SYSTEM_PROMPT_ID)

        llm_planner._log_llm_call(
            plan_id=run.plan_id,
            system_prompt="sys",
            user_prompt="usr",
            response_text="{}",
            model_used="gpt-4o-mini",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=120,
            prompt_id=prompt_id,
            prompt_version=version,
        )

        row = DeepRunLog.objects.get(deep_run=run, event_type="llm_call")
        # The full tuple on ONE row: agent, prompt version, model.
        assert row.agent_type == "planner"
        assert row.model_used == "gpt-4o-mini"
        assert row.prompt_id == "planner.system"
        assert row.prompt_version == version
        assert row.prompt_version != ""

    def test_the_stamp_follows_a_pinned_prompt_version(self, user_factory, workspace_factory, monkeypatch):
        """A pinned eval must not stamp its rows with the ACTIVE version.

        ``run_planner_eval --version v11`` reassigns ``SYSTEM_PROMPT_TEMPLATE``.
        If the version stamp were resolved independently it would keep saying
        "v12", and the eval's own telemetry would attribute v11's results to
        v12 — a measurement that lies about its own configuration is worse than
        no measurement.
        """
        from components.agents.infrastructure.adapters.langchain.deep import llm_planner

        run = _run(user_factory, workspace_factory)
        monkeypatch.setattr(llm_planner, "SYSTEM_PROMPT_VERSION", "v1")

        llm_planner._log_llm_call(
            plan_id=run.plan_id,
            system_prompt="sys",
            user_prompt="usr",
            response_text="{}",
            model_used="gpt-4o-mini",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
            prompt_id=llm_planner.PLANNER_SYSTEM_PROMPT_ID,
            prompt_version=llm_planner.SYSTEM_PROMPT_VERSION,
        )

        assert DeepRunLog.objects.get(deep_run=run).prompt_version == "v1"

    def test_an_unstamped_call_stays_blank_rather_than_defaulting(self, user_factory, workspace_factory):
        from components.agents.infrastructure.adapters.langchain.deep import llm_planner

        run = _run(user_factory, workspace_factory)
        llm_planner._log_llm_call(
            plan_id=run.plan_id,
            system_prompt="sys",
            user_prompt="usr",
            response_text="{}",
            model_used="gpt-4o-mini",
            prompt_tokens=None,
            completion_tokens=None,
            latency_ms=1,
        )
        row = DeepRunLog.objects.get(deep_run=run, event_type="llm_call")
        assert row.prompt_id == ""
        assert row.prompt_version == ""


class TestTheSpecialistRowCarriesTheTuple:
    def test_a_tool_observation_records_the_specialists_prompt_version(self, user_factory, workspace_factory):
        from components.agents.infrastructure.gateways.deep.logging import log_deep_event

        run = _run(user_factory, workspace_factory)
        prompt_id, version = specialist_prompt_stamp("code_security_agent")
        assert version, "code_security_agent.system must be a registered, versioned prompt"

        log_deep_event(
            run.thread_id,
            "tool_observation",
            status="ok",
            agent_type="CodeSecurityAgent",
            tool_name="analyse_code_finding",
            payload={"tool_input": "{}"},
            prompt_id=prompt_id,
            prompt_version=version,
        )

        row = DeepRunLog.objects.get(deep_run=run, event_type="tool_observation")
        assert row.prompt_id == "code_security_agent.system"
        assert row.prompt_version == version

    def test_every_registered_specialist_prompt_resolves_a_version(self):
        """A registered prompt with no resolvable version would stamp blank silently."""
        from components.agents.infrastructure.prompts.registry import PromptRegistry

        unresolved = [
            prompt_id
            for prompt_id in PromptRegistry.all_prompt_ids()
            if prompt_id.endswith(".system") and not prompt_stamp(prompt_id)[1]
        ]
        assert not unresolved, f"registered system prompts with no active version: {unresolved}"
