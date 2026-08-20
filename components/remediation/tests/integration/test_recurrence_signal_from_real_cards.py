"""The recurrence signal, driven end to end from cards the real writers emit.

ADR 0032 §1.3.3 / Phase 0.2. ``BoardFindingFactsRepository`` read
``payload["fingerprint"]``. **No card builder writes that key** — the board
convention is ``payload["lookup_key"]``, set by every entry in
``finding_raised_board_handler._SOURCE_BOARD`` and threaded into the task's
``idempotency_key``. So ``FindingRemediationFacts.finding_fingerprint`` was
``""`` for every card, the guard in
``PropagateRemediationOutcomesUseCase`` (``if fp and …``) was ``False`` for
every prior, and every prior fell to the ``else`` branch and was awarded
``record_reuse_success`` (+3) — when the correct verdict was
``record_recurrence`` (−5). **The sign was inverted: a fix that did not hold
was promoted in retrieval ranking rather than demoted.**

The suite stayed green over that dead branch because every existing test
hand-built ``payload={"fingerprint": …}``, i.e. it manufactured the key it was
meant to detect. **Nothing here constructs a payload.** Every card comes out of
``handle_finding_raised_board`` — the same function production calls — and every
fact is read by the real ``BoardFindingFactsRepository``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import mock
from uuid import uuid4

import pytest

from components.agents.application.handlers.finding_raised_board_handler import (
    _SOURCE_BOARD,
    handle_finding_raised_board,
)
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.infrastructure.repositories.django_finding_repository import (
    DjangoFindingRepository,
)
from components.remediation.application.commands.record_remediation_entry_command import (
    RecordRemediationEntryCommand,
)
from components.remediation.application.providers.remediation_provider import (
    build_remediation_service,
)
from components.remediation.infrastructure.adapters.board_finding_facts_repository import (
    BoardFindingFactsRepository,
)
from components.remediation.infrastructure.repositories.remediation_entry_repository import (
    DjangoRemediationEntryRepository,
)
from components.remediation.tests.unit.fakes import FakeSignOffGate
from components.shared_kernel.domain.events import FindingRaised
from components.shared_kernel.domain.security import FindingStatus, Severity

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
_PR = "https://github.com/acme/repo/pull/7"

# Enough attributes to satisfy every builder in ``_SOURCE_BOARD``; each one
# reads the subset it cares about and ignores the rest.
_ATTRS = {
    "check_id": "iam_root_mfa_enabled",
    "account_id": "123456789012",
    "resource_uid": "arn:aws:iam::123456789012:root",
    "resource_name": "root",
    "resource_type": "AwsIamUser",
    "region": "us-east-1",
    "service": "iam",
    "rule_id": "python.lang.security.audit.exec-detected",
    "rule_source": "opengrep",
    "repo": "acme/repo",
    "commit_sha": "deadbeef",
    "path": "app/views.py",
    "start_line": 42,
    "end_line": 43,
    "cwe": ["CWE-94"],
    "language": "python",
    "confidence": "high",
    "package": "openssl",
    "installed_version": "1.1.1",
    "fixed_version": "1.1.1w",
    "cve_id": "CVE-2023-0286",
    "image": "acme/api:latest",
    "domain": "acme.example",
    "project_name": "acme-web",
    "path_legs": [],
    "entry_point": "0.0.0.0/0",
    "agent_type": "triage_agent",
    "impact_score": 90,
    "action_type": "log_watch",
    "detector_slug": "logwatch.error",
    "board_context": {"evidence": []},
}


def _logwatch_board_payload(fingerprint: str) -> dict:
    """What ``finding_observed_bridge`` actually stores for a log-watch finding.

    ``ErrorFinding.as_contract()``, spread by the detector — deliberately WITHOUT
    a ``lookup_key``, because ``_build_logwatch_card`` supplies it via
    ``setdefault``.

    It DOES carry the retired ``fingerprint`` copy, reproducing the contract as
    it stood before this change. Two reasons that is the right fixture: log-watch
    is the one source whose payload happened to carry that second copy — which is
    why the recurrence branch looked reachable and the drift went unnoticed — and
    every log-watch card already in the database still has it. The reader must
    land on ``lookup_key`` anyway.
    """
    return {
        "fingerprint": fingerprint,
        "signal": "ERROR spike in web",
        "service": "web",
        "level": "ERROR",
        "severity": "critical",
        "evidence": [{"type": "log", "detail": "ERROR ... traceback ..."}],
        "blast_radius": {"service": "web", "level": "ERROR", "window_records": 12},
        "confidence": "high",
        "probable_cause": "",
        "suggested_fix": "",
        "recommendation": "",
        "triage": {"status": "pending"},
    }


@pytest.fixture(autouse=True)
def _flags_on():
    """Pin every feature flag ON so the flag-gated sources (logwatch) file cards.

    Mirrors ``test_logwatch_board_cutover._cutover`` — the flag is orthogonal to
    what is under test here, and a DB flag + shared Redis cache is not
    deterministic in a test run.
    """
    stub = mock.Mock()
    stub.is_feature_enabled.return_value = True
    with mock.patch(
        "components.shared_platform.application.providers.feature_flags_provider.get_feature_flags_provider",
        return_value=stub,
    ):
        yield


def _raise_finding(workspace, *, source: str, fingerprint: str):
    """Seed an SSOT finding and file its card through the REAL board writer."""
    from infrastructure.persistence.project.models import Task

    attributes = dict(_ATTRS)
    attributes["board_payload"] = _logwatch_board_payload(fingerprint)
    finding = FindingEntity(
        id=uuid4(),
        workspace_id=workspace.id,
        source=source,
        fingerprint=fingerprint,
        asset_urn=f"urn:test:{fingerprint}",
        severity=Severity.CRITICAL,  # above every source's board floor
        status=FindingStatus.OPEN,
        title="Root account without MFA",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
        description="Seeded by the recurrence-signal test.",
        remediation="Enable MFA on the root account.",
        compliance={"CIS-2.0": ["1.5"]},
        attributes=attributes,
    )
    DjangoFindingRepository().upsert(finding)
    # ``upsert`` is keyed on (workspace, source, fingerprint), so re-raising the
    # SAME finding updates the existing row and keeps its original id — exactly
    # what happens when a finding recurs. Read the id back rather than assuming
    # the one we minted survived.
    from infrastructure.persistence.findings.models import Finding as FindingRow

    finding_id = FindingRow.unscoped.get(workspace_id=workspace.id, source=source, fingerprint=fingerprint).id

    handle_finding_raised_board(
        FindingRaised(
            workspace_id=finding.workspace_id,
            finding_id=finding_id,
            fingerprint=finding.fingerprint,
            asset_urn=finding.asset_urn,
            severity=finding.severity.value,
            status=finding.status.value,
            source=source,
            title=finding.title,
            is_new=True,
        )
    )

    source_type = _SOURCE_BOARD[source]["source_type"]
    task = Task.objects.filter(workspace=workspace, source_type=source_type).order_by("-created_at").first()
    assert task is not None, f"the real writer filed no card for source {source}"
    return finding, task


def _make_remediable(task):
    """Bring a freshly-filed card to the state the entry gate admits.

    Only the two facts the gate needs are added — a draft PR (written by
    ``open_draft_pr_use_case``) and a resolved marker (written by
    ``ResolveFindingTaskRepository``). The card's own payload, including the
    fingerprint key under test, is left exactly as the writer emitted it.
    """
    metadata = dict(task.metadata or {})
    payload = dict(metadata.get("payload") or {})
    payload["draft_pr"] = {"url": _PR, "repo": "acme/repo", "branch": "fix/x"}
    metadata["payload"] = payload
    metadata["triage"] = {"status": "resolved"}
    task.metadata = metadata
    task.save(update_fields=["metadata"])
    return task


def _service():
    return build_remediation_service(
        store=DjangoRemediationEntryRepository(),
        sign_off_gate=FakeSignOffGate(approved=True),
        finding_facts=BoardFindingFactsRepository(),
    )


def _record(service, workspace, task, *, code="fix()"):
    return service.record(
        RecordRemediationEntryCommand(
            workspace_id=workspace.id,
            finding_task_id=str(task.id),
            sign_off_artifact_type="remediation",
            sign_off_artifact_id="signoff-1",
            pr_applied=True,
            applied_pr_url=_PR,
            code=code,
            language="python",
            title="Fix",
        )
    )


class TestEveryBoardSourceCarriesAReadableFingerprint:
    """The fitness test ADR 0032 D6 asks for: a fingerprint-less card fails.

    Parametrized over ``_SOURCE_BOARD`` itself, so a source added later is
    covered the moment it is registered — the reader cannot silently go blind
    on a new pillar.
    """

    @pytest.mark.parametrize("source", sorted(_SOURCE_BOARD))
    def test_the_facts_reader_sees_the_cards_identity(self, source, workspace_factory):
        workspace = workspace_factory()
        finding, task = _raise_finding(workspace, source=source, fingerprint=f"fp-{source}")

        facts = BoardFindingFactsRepository().get_facts(workspace_id=str(workspace.id), finding_task_id=str(task.id))

        assert facts.exists is True
        card_identity = (task.metadata or {}).get("payload", {}).get("lookup_key")
        assert card_identity, f"{source} filed a card with no lookup_key"
        assert facts.finding_fingerprint == card_identity, (
            f"{source}: the facts reader did not read the identity the writer emitted"
        )
        assert facts.finding_fingerprint != ""

    def test_the_legacy_key_alone_is_not_honoured(self, workspace_factory, team_factory):
        """Pins the convergence, so nobody re-adds ``or payload["fingerprint"]``.

        A card carrying ONLY the retired key must read as "no identity" —
        otherwise two live names for one value creep back and the next drift is
        invisible again (ADR 0032 D6: converge the key, do not add a fallback).
        """
        from infrastructure.persistence.project.models import Column, Task

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        column = Column.objects.create(
            team=team, workspace=workspace, project=None, title="Backlog", order=0, created_by=owner
        )
        task = Task.objects.create(
            team=team,
            workspace=workspace,
            column=column,
            created_by=owner,
            title="[FINDING] legacy shape",
            source_type="ai.log_watch",
            metadata={"payload": {"fingerprint": "fp-legacy-only"}},
        )

        facts = BoardFindingFactsRepository().get_facts(workspace_id=str(workspace.id), finding_task_id=str(task.id))

        assert facts.finding_fingerprint == ""

    @pytest.mark.parametrize("source", sorted(_SOURCE_BOARD))
    def test_the_recorded_entry_carries_that_identity(self, source, workspace_factory, team_factory):
        """The fingerprint must survive into the corpus row, not just the facts DTO."""
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        workspace = workspace_factory()
        _finding, task = _raise_finding(workspace, source=source, fingerprint=f"fp-{source}")
        _make_remediable(task)

        entry = _record(_service(), workspace, task)

        assert Row.objects.get(id=entry.id).finding_fingerprint != ""


class TestOutcomeVerdictFromRealCards:
    def test_the_same_finding_returning_scores_recurrence_not_reuse_success(self, workspace_factory):
        """The inverted signal, asserted on the stored counters.

        A recurrence means the card was cleared and the finding came back: the
        board's ``idempotency_key`` (``lookup_key:<identity>``) permanently binds
        one card per identity per source, so the second card only exists once the
        first is gone. That is exactly the shape the recurrence branch is for.
        """
        from infrastructure.persistence.project.models import Task
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        workspace = workspace_factory()
        service = _service()

        _f1, first_task = _raise_finding(workspace, source="code_security.opengrep", fingerprint="fp-RECURS")
        _make_remediable(first_task)
        first = _record(service, workspace, first_task)
        baseline = Row.objects.get(id=first.id).score

        # The card is cleared off the board, then the SAME finding is raised again.
        Task.objects.filter(id=first_task.id).delete()
        _f2, second_task = _raise_finding(workspace, source="code_security.opengrep", fingerprint="fp-RECURS")
        assert second_task.id != first_task.id
        _make_remediable(second_task)

        _record(service, workspace, second_task, code="fix_again()")

        first_row = Row.objects.get(id=first.id)
        assert first_row.recurrence_count == 1, "the fix did not hold — this must score recurrence"
        assert first_row.reuse_count == 0, "a fix that did not hold must never be credited with reuse"
        assert first_row.success_count == 0
        assert first_row.score < baseline

    def test_a_genuinely_reused_fix_still_scores_reuse_success(self, workspace_factory):
        """The allow side: a DIFFERENT finding of the same kind still credits the prior."""
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        workspace = workspace_factory()
        service = _service()

        _f1, task_a = _raise_finding(workspace, source="code_security.opengrep", fingerprint="fp-A")
        _make_remediable(task_a)
        first = _record(service, workspace, task_a)
        baseline = Row.objects.get(id=first.id).score

        _f2, task_b = _raise_finding(workspace, source="code_security.opengrep", fingerprint="fp-B")
        _make_remediable(task_b)
        _record(service, workspace, task_b, code="different_fix()")

        first_row = Row.objects.get(id=first.id)
        assert first_row.reuse_count == 1
        assert first_row.success_count == 1
        assert first_row.recurrence_count == 0
        assert first_row.score > baseline
