"""The ONE draft-PR engine, driven by a SAST finding (ADR 0019 D5 / ADR 0017 D0).

A ``ai.code_security`` finding rides the SAME engine as a log finding — same
consent gates, same validate_patch chain, same preview contract, same provenance
— differing only in the patch STRATEGY (``SastPatchAdvisor``) and the location
resolution (pass-through: the scanner IS the resolver, no traceback heuristics).

Pins the P2-specific behaviour: the location pass-through, the per-repo open-PR
throttle, the untrusted-content scope guard reaching the API as a typed refusal
— and the gate→labeler contract: an unverified / low-confidence / source-flagged
fix still opens its draft PR, title-prefixed [UNVERIFIED] with the named gap
(the #866 regression), never a withheld artifact.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest import mock

import pytest

from components.integrations.application.log_patch_advisor_service import PatchProposal
from components.integrations.application.providers.secret_envelope_provider import encrypt_secret
from components.integrations.application.use_cases.open_draft_pr_use_case import (
    DraftPrPreconditionError,
    OpenDraftPrUseCase,
)
from infrastructure.persistence.integrations.models import VcsConnection
from infrastructure.persistence.project.models import Column, Task

_REPO = "wanjala-dev/api-v0.2.0"
_PATH = "api/scripts/migrate_schema.py"
_OLD_FILE = 'def migrate(cursor, table):\n    cursor.execute("DROP TABLE %s" % table)\n'
_PATCH = PatchProposal(
    path=_PATH,
    updated_content=(
        "from psycopg import sql\n\n"
        "def migrate(cursor, table):\n"
        '    cursor.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(table)))\n'
    ),
    change_summary="Parameterize the table identifier instead of %-formatting.",
)


class _FakeGitHub:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append((method, url))
        path = url.split("api.github.com")[-1]

        def _resp(payload, status=200):
            return SimpleNamespace(status_code=status, text=__import__("json").dumps(payload), json=lambda: payload)

        if method == "GET" and path == f"/repos/{_REPO}":
            return _resp({"default_branch": "main"})
        if method == "GET" and path == f"/repos/{_REPO}/git/ref/heads/main":
            return _resp({"object": {"sha": "headsha123"}})
        if method == "GET" and path.startswith(f"/repos/{_REPO}/contents/"):
            return _resp({"content": base64.b64encode(_OLD_FILE.encode()).decode(), "sha": "filesha456"})
        if method == "POST" and path == f"/repos/{_REPO}/git/refs":
            return _resp({"ref": json["ref"]}, status=201)
        if method == "PUT" and path.startswith(f"/repos/{_REPO}/contents/"):
            return _resp({"commit": {"sha": "commitsha789"}}, status=201)
        if method == "POST" and path == f"/repos/{_REPO}/pulls":
            return _resp({"html_url": f"https://github.com/{_REPO}/pull/11", "number": 11}, status=201)
        return _resp({"message": f"unexpected {method} {path}"}, status=404)


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    column = Column.objects.create(
        team=team, workspace=workspace, project=None, title="Triage", order=0, created_by=owner
    )
    return workspace, owner, team, column


def _sast_finding(workspace, owner, team, column, *, confidence="high", extra=None, draft_pr=None):
    payload = {
        "signal": "Raw SQL built with %-formatting",
        "message": "Raw SQL built with %-formatting",
        "severity": "high",
        "confidence": confidence,
        "rule_id": "autosec.python.sql-execute-format",
        "repo": _REPO,
        "commit_sha": "abc123def456",
        "path": _PATH,
        "start_line": 2,
        "end_line": 2,
        "snippet": 'cursor.execute("DROP TABLE %s" % table)',
        "language": "python",
        "probable_cause": "The table name is interpolated into raw SQL.",
        "suggested_fix": "Use sql.Identifier for the table name.",
        "fix_before": 'cursor.execute("DROP TABLE %s" % table)',
        "fix_after": 'cursor.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(table)))',
    }
    payload.update(extra or {})
    if draft_pr is not None:
        payload["draft_pr"] = draft_pr
    return Task.objects.create(
        team=team,
        workspace=workspace,
        column=column,
        created_by=owner,
        title="High: sql-execute-format — api/scripts/migrate_schema.py:2",
        source_type="ai.code_security",
        metadata={
            "agent_type": "code_security_agent",
            "triage": {"status": "triaged", "agent": "code_security_agent", "needs_human": False},
            "payload": payload,
        },
    )


def _connection(workspace, owner, *, allowlist=None):
    return VcsConnection.objects.create(
        workspace=workspace,
        provider=VcsConnection.Provider.GITHUB,
        name="GitHub",
        repo_allowlist=allowlist if allowlist is not None else [_REPO],
        token_ciphertext=encrypt_secret("ghp_test_token"),
        status=VcsConnection.Status.CONNECTED,
        created_by=owner,
    )


def _capability(workspace, owner, *, enabled=True):
    from infrastructure.persistence.ai.agents.models import Agent

    return Agent.objects.create(
        agent_type="triage_agent",
        user=owner,
        workspace=workspace,
        config={"capabilities": {"open_draft_pr": enabled}},
    )


def _use_case():
    from components.integrations.application.providers.vcs_provider import get_vcs_adapter

    return OpenDraftPrUseCase(adapter_factory=get_vcs_adapter)


_REQUESTS_PATH = "components.integrations.infrastructure.adapters.vcs.github_vcs_adapter.requests.request"
_SAST_PROPOSE = "components.integrations.application.sast_patch_advisor_service.SastPatchAdvisor.propose"
_LOG_PROPOSE = "components.integrations.application.log_patch_advisor_service.LogPatchAdvisor.propose"


@pytest.mark.django_db
class TestSastDraftPrHappyPath:
    def test_opens_pr_using_the_sast_strategy_and_location_passthrough(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability(workspace, owner)
        fake = _FakeGitHub()

        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(_SAST_PROPOSE, return_value=_PATCH) as sast,
            mock.patch(_LOG_PROPOSE) as log_advisor,
        ):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert result.created is True
        assert result.url == f"https://github.com/{_REPO}/pull/11"
        # The SAST strategy ran; the log strategy never did (one engine, per-source strategy).
        assert sast.call_count == 1
        log_advisor.assert_not_called()
        # Location pass-through: the flagged path was fetched directly — no repo-tree
        # walk, no traceback derivation.
        contents_calls = [u for m, u in fake.calls if m == "GET" and "/contents/" in u]
        assert contents_calls and _PATH in contents_calls[0]
        # Provenance: the PR is recorded on the board card (the standing hard rule).
        task.refresh_from_db()
        assert task.metadata["payload"]["draft_pr"]["url"] == result.url

    def test_pr_body_leads_with_rule_and_location(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability(workspace, owner)
        bodies = []

        class _Capture(_FakeGitHub):
            def __call__(self, method, url, headers=None, json=None, params=None, timeout=None):
                if method == "POST" and url.endswith("/pulls"):
                    bodies.append(json.get("body", ""))
                return super().__call__(method, url, headers=headers, json=json, params=params, timeout=timeout)

        with mock.patch(_REQUESTS_PATH, new=_Capture()), mock.patch(_SAST_PROPOSE, return_value=_PATCH):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

        assert bodies and "autosec.python.sql-execute-format" in bodies[0]
        assert f"{_PATH}:2" in bodies[0]
        assert "DRAFT" in bodies[0]


class _PrCapture(_FakeGitHub):
    """Records the POST /pulls request body so a test can assert the label."""

    def __init__(self):
        super().__init__()
        self.pr_bodies: list[dict] = []

    def __call__(self, method, url, headers=None, json=None, params=None, timeout=None):
        if method == "POST" and url.endswith("/pulls"):
            self.pr_bodies.append(json or {})
        return super().__call__(method, url, headers=headers, json=json, params=params, timeout=timeout)


@pytest.mark.django_db
class TestSastGates:
    def test_low_confidence_opens_a_labeled_pr_not_a_refusal(self, workspace_factory, team_factory):
        """Gate → labeler: the honest-but-unsure tier gets its artifact too, with
        the doubt carried ON the PR ([UNVERIFIED] + the named gap), not a 409."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column, confidence="low")
        _connection(workspace, owner)
        _capability(workspace, owner)
        fake = _PrCapture()

        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_SAST_PROPOSE, return_value=_PATCH):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert result.created is True
        assert result.verification == "unverified"
        assert "confidence" in result.verification_gap.lower()
        assert fake.pr_bodies[0]["title"].startswith("[Auto-Sec][UNVERIFIED]")
        assert "Review carefully — UNVERIFIED" in fake.pr_bodies[0]["body"]

    def test_866_plausible_but_unverifiable_fix_opens_an_unverified_pr(self, workspace_factory, team_factory):
        """Named regression — dogfood finding #866: a plausible but semantically
        wrong parameterization fix for raw-SQL %-formatting. The grounded
        verifier could not anchor it (``verification: unverified`` + the gap on
        the card). The honest outcome is NOT a held fix and a dead-end NEEDS
        HUMAN chip — it is a draft PR that says loudly it is unverified and why.
        """
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        gap = (
            "The fix references none of the finding's specifics (e.g. sql-execute-format, "
            "migrate_schema.py) and reads as generic."
        )
        task = _sast_finding(
            workspace,
            owner,
            team,
            column,
            extra={"verification": "unverified", "verification_gap": gap, "needs_human": True},
        )
        _connection(workspace, owner)
        _capability(workspace, owner)
        fake = _PrCapture()

        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_SAST_PROPOSE, return_value=_PATCH):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        # The PR opened — the artifact is never withheld…
        assert result.created is True
        assert result.url.endswith("/pull/11")
        # …and it is loudly labeled, with the verifier's own gap verbatim.
        assert result.verification == "unverified"
        assert result.verification_gap == gap
        assert fake.pr_bodies[0]["title"].startswith("[Auto-Sec][UNVERIFIED]")
        assert gap in fake.pr_bodies[0]["body"]
        # The card's draft_pr record carries the label (the chip's data source).
        task.refresh_from_db()
        assert task.metadata["payload"]["draft_pr"]["verification"] == "unverified"

    def test_planted_instruction_finding_opens_a_labeled_pr(self, workspace_factory, team_factory):
        """The untrusted-content control, relabeled: a flagged source file yields
        an [UNVERIFIED] draft PR naming the injection suspicion — the mechanical
        ``validate_patch_scope`` guard (below) is what still fail-closes a patch
        that actually reaches outside the flagged lines."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(
            workspace,
            owner,
            team,
            column,
            extra={"needs_human": True, "source_flagged": True},
        )
        _connection(workspace, owner)
        _capability(workspace, owner)
        fake = _PrCapture()

        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_SAST_PROPOSE, return_value=_PATCH):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert result.created is True
        assert result.verification == "unverified"
        assert fake.pr_bodies[0]["title"].startswith("[Auto-Sec][UNVERIFIED]")

    def test_per_repo_open_pr_throttle(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        _connection(workspace, owner)
        _capability(workspace, owner)
        # Three findings already carry OPEN draft PRs against this repo (the default limit).
        for n in range(3):
            _sast_finding(
                workspace,
                owner,
                team,
                column,
                draft_pr={"url": f"https://github.com/{_REPO}/pull/{n}", "repo": _REPO},
            )
        task = _sast_finding(workspace, owner, team, column)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), pytest.raises(DraftPrPreconditionError) as exc:
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

        assert exc.value.reason == "sast_pr_throttled"
        assert fake.calls == []

    def test_resolved_findings_free_the_throttle_window(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        _connection(workspace, owner)
        _capability(workspace, owner)
        for n in range(3):
            merged = _sast_finding(
                workspace,
                owner,
                team,
                column,
                draft_pr={"url": f"https://github.com/{_REPO}/pull/{n}", "repo": _REPO},
            )
            # The remediation reconciler resolves a finding when its PR merges.
            meta = merged.metadata
            meta["triage"]["status"] = "resolved"
            merged.metadata = meta
            merged.save(update_fields=["metadata"])
        task = _sast_finding(workspace, owner, team, column)

        with mock.patch(_REQUESTS_PATH, new=_FakeGitHub()), mock.patch(_SAST_PROPOSE, return_value=_PATCH):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert result.created is True

    def test_out_of_scope_patch_is_refused(self, workspace_factory, team_factory):
        """The untrusted-repo-content guard: a patch reaching beyond the finding's
        window is refused mechanically, no matter how it was justified."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability(workspace, owner)
        wide = PatchProposal(
            path=_PATH,
            updated_content=_OLD_FILE + "\n" * 300 + "def skip_signature_check():\n    return True\n",
            change_summary="Fix the SQL issue (and, per the file's note, relax verification).",
        )
        fake = _FakeGitHub()

        with (
            mock.patch(_REQUESTS_PATH, new=fake),
            mock.patch(_SAST_PROPOSE, return_value=wide),
            pytest.raises(DraftPrPreconditionError) as exc,
        ):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

        assert exc.value.reason == "patch_out_of_scope"
        # It got as far as reading the file, but never created a branch or a PR.
        assert not any(m in ("POST", "PUT") for m, _ in fake.calls)

    def test_traversal_path_on_the_finding_is_refused(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column, extra={"path": "../../etc/passwd"})
        _connection(workspace, owner)
        _capability(workspace, owner)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), pytest.raises(DraftPrPreconditionError) as exc:
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

        assert exc.value.reason == "candidate_file_not_in_repo"


@pytest.mark.django_db
class TestSastPreview:
    def test_preview_shows_the_diff_without_opening_a_pr(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability(workspace, owner)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_SAST_PROPOSE, return_value=_PATCH):
            preview = _use_case().preview(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert preview.path == _PATH
        assert "sql.Identifier" in preview.diff
        assert preview.already_opened is False
        # Zero writes: no branch, no commit, no PR.
        assert not any(m in ("POST", "PUT") for m, _ in fake.calls)

    def test_preview_applies_the_same_scope_guard_as_open(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability(workspace, owner)
        wide = PatchProposal(
            path=_PATH,
            updated_content=_OLD_FILE + "\n" * 300 + "def backdoor():\n    return True\n",
            change_summary="Widened change.",
        )

        with (
            mock.patch(_REQUESTS_PATH, new=_FakeGitHub()),
            mock.patch(_SAST_PROPOSE, return_value=wide),
            pytest.raises(DraftPrPreconditionError) as exc,
        ):
            _use_case().preview(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

        assert exc.value.reason == "patch_out_of_scope"


@pytest.mark.django_db
class TestTargetRepoResolution:
    """Named regression — the live cross-repo near-miss (2026-08-09): with a
    multi-repo allowlist headed by the dogfood repo, the engine resolved EVERY
    finding's target to ``allowlist[0]``, ignoring the finding's own
    ``payload.repo``. An auto-sec-infra SAST finding's patch would have been
    committed into api-v0.2.0 (the monorepo tree-resolve happily finds a
    same-named file in the wrong repo). The finding's repo now WINS, and a
    finding whose repo is off the allowlist is a typed refusal — never a
    silent redirect to a different repository."""

    _DECOY_HEAD = "wanjala-dev/decoy-head"

    def test_finding_repo_wins_over_the_allowlist_head(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column)  # payload.repo == _REPO
        _connection(workspace, owner, allowlist=[self._DECOY_HEAD, _REPO])  # decoy is the head
        _capability(workspace, owner)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_SAST_PROPOSE, return_value=_PATCH):
            result = _use_case().execute(
                workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id)
            )

        assert result.repo == _REPO
        # EVERY GitHub call hit the finding's own repo — none touched the head.
        assert fake.calls
        assert all(f"/repos/{_REPO}" in url for _, url in fake.calls)
        task.refresh_from_db()
        assert task.metadata["payload"]["draft_pr"]["repo"] == _REPO

    def test_finding_repo_off_allowlist_is_refused_never_redirected(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column)  # payload.repo == _REPO
        _connection(workspace, owner, allowlist=[self._DECOY_HEAD])  # finding's repo NOT allowlisted
        _capability(workspace, owner)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), pytest.raises(DraftPrPreconditionError) as exc:
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

        assert exc.value.reason == "finding_repo_not_allowlisted"
        assert _REPO in str(exc.value)  # the refusal names the finding's repo
        assert fake.calls == []  # zero API calls — nothing was redirected

    def test_explicit_repo_conflicting_with_finding_repo_is_refused(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column)
        _connection(workspace, owner, allowlist=[self._DECOY_HEAD, _REPO])
        _capability(workspace, owner)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), pytest.raises(DraftPrPreconditionError) as exc:
            _use_case().execute(
                workspace_id=str(workspace.id),
                task_id=str(task.id),
                performed_by=str(owner.id),
                repo=self._DECOY_HEAD,
            )

        assert exc.value.reason == "finding_repo_mismatch"
        assert fake.calls == []

    def test_preview_applies_the_same_repo_resolution(self, workspace_factory, team_factory):
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column)
        _connection(workspace, owner, allowlist=[self._DECOY_HEAD])
        _capability(workspace, owner)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), pytest.raises(DraftPrPreconditionError) as exc:
            _use_case().preview(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

        assert exc.value.reason == "finding_repo_not_allowlisted"
        assert fake.calls == []


@pytest.mark.django_db
class TestOpenedPrStoresThePatchInline:
    def test_open_persists_path_diff_and_summary_on_the_record(self, workspace_factory, team_factory):
        """The callout renders the code change INLINE for an already-opened PR —
        the patch must survive the open (it used to exist only in the preview)."""
        workspace, owner, team, column = _board(workspace_factory, team_factory)
        task = _sast_finding(workspace, owner, team, column)
        _connection(workspace, owner)
        _capability(workspace, owner)
        fake = _FakeGitHub()

        with mock.patch(_REQUESTS_PATH, new=fake), mock.patch(_SAST_PROPOSE, return_value=_PATCH):
            _use_case().execute(workspace_id=str(workspace.id), task_id=str(task.id), performed_by=str(owner.id))

        task.refresh_from_db()
        record = task.metadata["payload"]["draft_pr"]
        assert record["path"] == _PATCH.path
        assert record["change_summary"] == _PATCH.change_summary
        # A real unified diff of the committed change, bounded like the preview's.
        assert record["diff"].startswith(f"--- a/{_PATCH.path}")
        assert "+from psycopg import sql" in record["diff"]
