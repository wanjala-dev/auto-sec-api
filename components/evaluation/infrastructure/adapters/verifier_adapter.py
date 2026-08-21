"""The deterministic half of grading (ADR 0033 D2).

An axis that can be decided mechanically must be, for two reasons that pull the
same way: an LLM asked "does this patch apply?" is both more expensive and less
correct than a parser, and a mechanical verdict is one a customer can re-derive
without trusting us.

This adapter is only the bridge. The checks themselves live in
`domain/services/verifiers.py`, framework-free and unit-tested there; all this
file does is find each check's INVENTORY — the ground truth it compares the
agent's output against — and translate the result onto the port.

Sourcing that inventory is the whole design question, because a wrong inventory
does not produce a wrong verdict, it produces a confident one:

  · `no_fabricated_asset` compares against this workspace's real CloudAsset
    URNs. Scoped to the workspace, always — another tenant's inventory would
    make a genuinely fabricated URN look real, which is the one failure this
    axis exists to catch.

  · `fix_applies` compares against the files the CASE declares. There is no
    repo-tree read here on purpose: fetching the tree per case would put a VCS
    round-trip inside the eval loop, and a stale tree would fail patches that
    are actually fine. A case that names no target files is NOT MEASURED, which
    the verifier already says in those words.

Both paths return NOT MEASURED rather than False whenever the inventory is
missing or empty. An empty asset inventory would make every reference look
fabricated — that is our gap, not the agent's, and scoring the agent for it
would be the manufactured-failure mode this whole subsystem is built to avoid.
"""

from __future__ import annotations

import logging

from components.evaluation.application.ports.eval_ports import (
    AgentOutcome,
    AxisVerdict,
    EvalCaseInput,
    VerifierPort,
)
from components.evaluation.domain.services.verifiers import (
    Outcome,
    VerificationResult,
    verify_fix_applies,
    verify_no_fabricated_asset,
)

logger = logging.getLogger(__name__)

#: Only these axes are mechanical. Anything else belongs to the judge, and
#: `supports()` returning False is what routes it there.
DETERMINISTIC_AXES = ("fix_applies", "no_fabricated_asset")

#: Where a mined case tends to carry the file(s) a patch should touch. Findings
#: from different scanners spell this differently, so read all of them rather
#: than picking one and silently not-measuring the rest.
_TARGET_FILE_KEYS = ("target_files", "file_path", "file", "path", "location", "filename")


class DeterministicVerifierAdapter(VerifierPort):
    """Runs the mechanical axes for one workspace's evaluation run."""

    def __init__(self, *, workspace_id, asset_inventory_reader=None) -> None:
        self._workspace_id = workspace_id
        self._read_assets = asset_inventory_reader or _read_workspace_asset_urns
        self._asset_cache: tuple[str, ...] | None = None

    def supports(self, axis: str) -> bool:
        return axis in DETERMINISTIC_AXES

    def verify(self, *, axis: str, case: EvalCaseInput, outcome: AgentOutcome) -> AxisVerdict:
        """Never raises. A verifier that explodes leaves its axis unmeasured —
        the runner treats a raised exception the same way, but saying it here
        keeps the reason specific instead of generic."""
        try:
            if axis == "no_fabricated_asset":
                result = verify_no_fabricated_asset(outcome.output, self._asset_urns())
            elif axis == "fix_applies":
                result = verify_fix_applies(outcome.output, _declared_target_files(case))
            else:
                # supports() gates this, so reaching here means the two lists
                # drifted apart. Unmeasured, not passed.
                return AxisVerdict(
                    axis=axis,
                    passed=None,
                    reason=f"No deterministic check is registered for '{axis}'.",
                )
        except Exception as exc:
            logger.exception("eval_verifier_failed axis=%s case=%s", axis, case.case_id)
            return AxisVerdict(axis=axis, passed=None, reason=f"The deterministic check raised: {exc}")

        return _to_verdict(result)

    def _asset_urns(self) -> tuple[str, ...]:
        """Read once per run, not once per case — the inventory does not change
        mid-run, and a suite of 50 cases would otherwise fire 50 identical
        queries."""
        if self._asset_cache is None:
            self._asset_cache = tuple(self._read_assets(self._workspace_id))
        return self._asset_cache


def _to_verdict(result: VerificationResult) -> AxisVerdict:
    """Three domain states onto the port's `bool | None`.

    NOT_MEASURED must become None, never False. Collapsing it to False is
    precisely how an unassessed axis becomes a reported defect.
    """
    if result.outcome is Outcome.NOT_MEASURED:
        return AxisVerdict(axis=result.axis, passed=None, reason=result.reason)
    return AxisVerdict(axis=result.axis, passed=result.passed, reason=result.reason)


def _declared_target_files(case: EvalCaseInput) -> tuple[str, ...] | None:
    """The files this case says a patch should touch.

    Returns None — not an empty tuple — when the case declares nothing, so the
    verifier reports "no inventory was supplied" rather than "the inventory is
    empty". They read the same to a machine and differently to an operator.
    """
    inputs = case.prompt_inputs or {}
    found: list[str] = []
    for key in _TARGET_FILE_KEYS:
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value.strip())
        elif isinstance(value, (list, tuple)):
            found.extend(str(v).strip() for v in value if str(v).strip())

    if not found:
        return None
    # Order-stable dedupe: the same path often arrives under two keys.
    return tuple(dict.fromkeys(found))


def _read_workspace_asset_urns(workspace_id) -> tuple[str, ...]:
    """This workspace's known asset URNs, from the cloud graph.

    Imported inside the function so the module stays importable without Django
    configured — the domain verifiers it wraps have no such dependency, and the
    unit tests inject a reader instead.
    """
    from infrastructure.persistence.cloud_graph.models import CloudAsset

    return tuple(
        CloudAsset.objects.filter(workspace_id=workspace_id)
        .exclude(asset_urn="")
        .values_list("asset_urn", flat=True)
        .distinct()
    )


__all__ = ["DETERMINISTIC_AXES", "DeterministicVerifierAdapter"]
