"""Authoring a suite from the product, end to end.

Two things are being pinned. The first is that writing a suite is an ADMIN act
while reading stays open to members — the split D11 settled, now applied to a
route that both writes and creates something runnable.

The second is that a rejected upload writes NOTHING. That is easy to get wrong
in a way nobody notices: a partial import leaves a suite whose contents differ
from the file that made it, and every score it ever produces is computed over a
dataset the author never approved.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from infrastructure.persistence.evaluation.models import EvalCase, EvalSuite
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _member(workspace, user, role="admin"):
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role,
        persona="contributor",
        status=WorkspaceMembership.Status.ACTIVE,
    )


@pytest.fixture
def people(workspace_factory, user_factory):
    workspace = workspace_factory(owner=user_factory())
    admin, viewer, outsider = user_factory(), user_factory(), user_factory()
    _member(workspace, admin, role="admin")
    _member(workspace, viewer, role="member")
    return {"ws": workspace, "admin": admin, "viewer": viewer, "outsider": outsider}


def _as(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _url(people, name="evaluation:eval-suite-create"):
    return reverse(name, kwargs={"workspace_id": people["ws"].id})


def _payload(**over):
    body = {
        "name": "My triage cases",
        "agent_type": "triage",
        "axes": ["grounded"],
        "cases": [
            {"scenario": "public bucket", "prompt_inputs": {"title": "S3 public"}},
            {"scenario": "open security group", "prompt_inputs": {"title": "0.0.0.0/0"}},
        ],
    }
    body.update(over)
    return body


class TestWhoMayAuthor:
    def test_an_admin_can_create_a_suite(self, people):
        response = _as(people["admin"]).post(_url(people), _payload(), format="json")

        assert response.status_code == 201
        assert response.data["accepted"] == 2

    def test_a_member_cannot(self, people):
        """Reading is open to members (D11); creating something runnable is not."""
        response = _as(people["viewer"]).post(_url(people), _payload(), format="json")

        assert response.status_code == 403
        assert EvalSuite.objects.count() == 0

    def test_an_outsider_cannot(self, people):
        response = _as(people["outsider"]).post(_url(people), _payload(), format="json")

        assert response.status_code == 403


class TestNothingIsWrittenOnRejection:
    def test_a_bad_row_leaves_no_suite_behind(self, people):
        payload = _payload(cases=[{"scenario": "fine"}, {"scenario": ""}])

        response = _as(people["admin"]).post(_url(people), payload, format="json")

        assert response.status_code == 400
        assert EvalSuite.objects.count() == 0
        assert EvalCase.objects.count() == 0

    def test_the_response_names_the_offending_row(self, people):
        payload = _payload(cases=[{"scenario": "fine"}, {"scenario": ""}])

        response = _as(people["admin"]).post(_url(people), payload, format="json")

        assert response.data["errors"][0]["row"] == 2

    def test_a_suite_with_no_name_is_refused(self, people):
        response = _as(people["admin"]).post(_url(people), _payload(name=""), format="json")

        assert response.status_code == 400
        assert "name" in response.data["errors"][0]["message"].lower()

    def test_a_suite_with_no_axes_is_refused(self, people):
        """An axis is what each case is graded on. Zero axes means every case
        would come back NOT MEASURED — a run that costs money to learn nothing."""
        response = _as(people["admin"]).post(_url(people), _payload(axes=[]), format="json")

        assert response.status_code == 400


class TestProvenanceIsRecorded:
    def test_the_suite_is_marked_authored(self, people):
        _as(people["admin"]).post(_url(people), _payload(), format="json")

        suite = EvalSuite.objects.get()
        assert suite.origin == EvalSuite.Origin.AUTHORED
        assert suite.mode == EvalSuite.Mode.AGENT

    def test_every_case_is_marked_authored(self, people):
        _as(people["admin"]).post(_url(people), _payload(), format="json")

        assert EvalCase.objects.count() == 2
        assert {c.source_kind for c in EvalCase.objects.all()} == {EvalCase.SourceKind.AUTHORED}

    def test_cases_left_without_a_source_ref_do_not_collide(self, people):
        """`(suite, source_kind, source_ref)` is unique. Two blank refs would
        collapse two distinct cases into one on insert."""
        payload = _payload(cases=[{"scenario": "a"}, {"scenario": "b"}, {"scenario": "c"}])

        response = _as(people["admin"]).post(_url(people), payload, format="json")

        assert response.status_code == 201
        assert EvalCase.objects.count() == 3

    def test_duplicates_are_reported_back_to_the_author(self, people):
        payload = _payload(cases=[{"scenario": "same"}, {"scenario": "same"}, {"scenario": "same"}])

        response = _as(people["admin"]).post(_url(people), payload, format="json")

        assert response.data["accepted"] == 1
        assert response.data["duplicates_collapsed"] == 2


class TestPromptMode:
    def test_prompt_mode_requires_a_system_prompt(self, people):
        """The mode exists to test a prompt. An empty one produces a run that
        grades nothing and reports it as a score."""
        response = _as(people["admin"]).post(_url(people), _payload(mode="prompt"), format="json")

        assert response.status_code == 400
        assert "system prompt" in response.data["errors"][0]["message"].lower()

    def test_agent_mode_refuses_a_system_prompt_rather_than_ignoring_it(self, people):
        """Silently ignoring it would let someone believe they were testing
        their edited prompt while the agent's own prompt actually ran."""
        payload = _payload(system_prompt="You are a careful triage analyst.")

        response = _as(people["admin"]).post(_url(people), payload, format="json")

        assert response.status_code == 400
        assert "prompt mode" in response.data["errors"][0]["message"].lower()

    def test_a_prompt_suite_stores_its_prompt_and_what_it_was_forked_from(self, people):
        payload = _payload(
            mode="prompt",
            system_prompt="You are a careful triage analyst.",
            forked_from_prompt_id="triage_agent.system@v4",
        )

        response = _as(people["admin"]).post(_url(people), payload, format="json")

        assert response.status_code == 201
        suite = EvalSuite.objects.get()
        assert suite.mode == EvalSuite.Mode.PROMPT
        assert suite.system_prompt.startswith("You are a careful")
        assert suite.forked_from_prompt_id == "triage_agent.system@v4"

    def test_editing_the_prompt_changes_the_dataset_version(self, people):
        """The prompt IS the question in this mode. If it did not participate in
        the fingerprint, rewriting it and re-running would read as the model
        changing — the exact confusion the fingerprint exists to prevent."""
        from components.evaluation.infrastructure.repositories.eval_repository import DjangoEvalRepository

        _as(people["admin"]).post(_url(people), _payload(mode="prompt", system_prompt="version one"), format="json")
        suite = EvalSuite.objects.get()
        repo = DjangoEvalRepository()
        before = repo.suite_dataset_hash(suite_id=str(suite.id), workspace_id=str(people["ws"].id))

        suite.system_prompt = "version two, materially different"
        suite.save(update_fields=["system_prompt"])
        after = repo.suite_dataset_hash(suite_id=str(suite.id), workspace_id=str(people["ws"].id))

        assert before != after


class TestTemplate:
    def test_a_member_may_fetch_the_template(self, people):
        response = _as(people["viewer"]).get(_url(people, "evaluation:eval-case-template"))

        assert response.status_code == 200
        assert response.data["template"]["cases"]

    def test_the_template_round_trips_through_the_create_endpoint(self, people):
        """If the worked example we hand people does not import, the first thing
        every user does fails."""
        template = _as(people["admin"]).get(_url(people, "evaluation:eval-case-template")).data["template"]

        response = _as(people["admin"]).post(_url(people), _payload(cases=template["cases"]), format="json")

        assert response.status_code == 201

    def test_the_template_states_the_self_authored_limit(self, people):
        """Someone reading the template is about to author a suite — that is the
        moment to say what its results can and cannot support."""
        response = _as(people["admin"]).get(_url(people, "evaluation:eval-case-template"))

        assert any("DIRECTIONAL" in note for note in response.data["notes"])
