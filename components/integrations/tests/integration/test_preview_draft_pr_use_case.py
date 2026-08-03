"""Integration tests — preview-before-commit (ADR 0012 P6).

The operator sees the grounded proposed patch + its grounding provenance BEFORE any
draft PR is opened. Asserts the load-bearing P6 claims:

* preview SURFACES the diff + change summary + grounding sources;
* preview POSTS the preview to the board (``payload.proposed_patch`` + provenance
  event + a card comment) — every AI action shows on the card;
* preview does NOT open a PR (no branch/commit/pulls calls) — grounds, never commits;
* preview STILL runs the ``validate_patch`` guardrail (D2): a destructive patch raises
  the same ``patch_removes_definitions`` here and writes nothing / opens nothing.

Reuses the open-draft-PR integration harness (real DB; GitHub HTTP stubbed at
``requests.request``; the patch LLM stubbed at ``LogPatchAdvisor.propose``).
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.application.log_patch_advisor_service import PatchProposal
from components.integrations.application.use_cases.open_draft_pr_use_case import (
    DraftPrPreconditionError,
    OpenDraftPrUseCase,
)
from components.integrations.tests.integration.test_open_draft_pr_use_case import (
    _PATCH,
    _PROPOSE_PATH,
    _REQUESTS_PATH,
    _board,
    _capability_agent,
    _connection,
    _FakeGitHub,
    _triaged_finding,
)
from components.remediation.application.ports.remediation_retrieval_port import (
    RemediationGroundingDTO,
)
from infrastructure.persistence.project.models import Task, TaskComment

_PRIOR = RemediationGroundingDTO(
    finding_kind="log_watch",
    language="python",
    title="Prior casing fix",
    summary="added an alias instead of deleting the module",
    code="AiEmbeddingsProvider = AIEmbeddingsProvider",
    tags=("import",),
    score=0.9,
    rating=5,
)


class _FakeRetrieval:
    def retrieve_grounding(self, *, workspace_id, finding_kind, query_text, top_k=3):
        return [_PRIOR]


def _use_case():
    from components.integrations.application.providers.vcs_provider import get_vcs_adapter

    return OpenDraftPrUseCase(adapter_factory=get_vcs_adapter, grounding_retrieval=_FakeRetrieval())


@pytest.mark.django_db
class TestPreviewDraftPr:
    def test_surfaces_patch_and_grounding_and_records_board_without_opening_pr(
        self, workspace_factory, team_factory
    ):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_PROPOSE_PATH, return_value=_PATCH):
            result = _use_case().preview(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        # Surfaced: the diff + change summary + grounding sources.
        assert result.already_opened is False
        assert result.path == _PATCH.path
        assert "run_due_schedules" in result.diff
        assert result.change_summary == _PATCH.change_summary
        assert len(result.grounding) == 1
        assert result.grounding[0]["title"] == "Prior casing fix"
        assert result.grounding[0]["rating"] == 5

        # NEVER opened a PR — no branch/commit/pulls calls (grounds, never commits, D2).
        paths = [u.split("api.github.com")[-1] for _, u in fake.calls]
        methods = [m for m, _ in fake.calls]
        assert not any(m == "POST" and p.endswith("/pulls") for m, p in zip(methods, paths))
        assert not any(m == "POST" and p.endswith("/git/refs") for m, p in zip(methods, paths))

        # Posted to the board (provenance): proposed_patch + event + comment.
        task.refresh_from_db()
        proposed = (task.metadata.get("payload") or {}).get("proposed_patch") or {}
        assert proposed.get("path") == _PATCH.path
        assert "draft_pr" not in (task.metadata.get("payload") or {})  # no PR was opened
        events = (task.metadata.get("provenance") or {}).get("events") or []
        assert any("previewed a proposed fix" in (e.get("action") or "") for e in events)
        assert TaskComment.objects.filter(task=task, comment__icontains="Proposed-fix preview").exists()

    def test_destructive_patch_fails_the_guardrail_in_preview(self, workspace_factory, team_factory):
        # D2: preview does not bypass validate_patch — a patch that drops the finding's
        # symbol raises the SAME precondition here, and nothing is written / opened.
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability_agent(workspace, owner)
        fake = _FakeGitHub()

        destructive = PatchProposal(
            path="components/workflow/application/service.py",
            updated_content="from x import run_due_schedules\n",  # deletes top-level handler()
            change_summary="gut the module",
        )
        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(_PROPOSE_PATH, return_value=destructive),
            pytest.raises(DraftPrPreconditionError) as exc,
        ):
            _use_case().preview(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert exc.value.reason == "patch_removes_definitions"
        task.refresh_from_db()
        assert "proposed_patch" not in (task.metadata.get("payload") or {})

    def test_preview_returns_existing_pr_when_already_opened(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _triaged_finding(
            workspace,
            owner,
            team,
            column,
            extra_payload={"draft_pr": {"url": "https://github.com/o/r/pull/9", "repo": "o/r"}},
        )
        _connection(workspace, owner)
        _capability_agent(workspace, owner)

        result = _use_case().preview(
            workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
        )
        assert result.already_opened is True
        assert result.pr_url == "https://github.com/o/r/pull/9"
