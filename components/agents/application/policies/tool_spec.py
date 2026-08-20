"""ADR 0031 — the agent tool declaration (`ToolSpec`) and its vocabulary.

The framework has no way to know what a tool *is*. Every cross-cutting property
— how it binds tenancy, whether it writes provenance, what its failure looks
like, which finding kinds it handles — lives in the tool author's memory rather
than in a declaration the registry can check. `ToolSpec` is that declaration.

**Phase 1 is observe-only and every field is optional.** A tool that declares
nothing gets `UNDECLARED`, and `UNDECLARED` must behave byte-identically to a
tool that predates this module: the risk tier still resolves through
``tool_risk.resolve_tool_risk`` exactly as before, nothing is gated on `scope`,
and no fitness function fails. The declaration becomes mandatory in ADR 0031
Phase 3 (F1), one concern at a time.

Framework-free by construction — this module imports nothing from Django,
LangChain, or `infrastructure/`. It is the shared vocabulary that the `@tool`
decorator (infrastructure) and the governance middleware (infrastructure) both
read, so the meaning of a declaration lives in the application layer where the
policy belongs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from components.agents.domain.errors import InvalidToolDeclarationError


class Scope:
    """How a tool binds tenancy (ADR 0031 D1)."""

    #: Every query filters ``workspace_id = <the run's bound workspace>``.
    #: The default and the overwhelming majority.
    WORKSPACE_BOUND = "workspace_bound"

    #: Genuinely tenant-independent (IOC enrichment against external threat
    #: intel, a pure text grader). Must justify itself in the docstring.
    WORKSPACE_FREE = "workspace_free"

    #: Reads beyond one tenant. Reserved for staff/support surfaces; no tool
    #: holds it today and adding one is a security review.
    CROSS_WORKSPACE = "cross_workspace"

    ALL = (WORKSPACE_BOUND, WORKSPACE_FREE, CROSS_WORKSPACE)


class Provenance:
    """What audit trail a tool leaves behind (ADR 0031 D5)."""

    #: Leaves no board card and no audit row (the read tools).
    NONE = "none"

    #: Routes through ``_finding_processing.process_pending_finding`` and
    #: lands a card on the workspace board.
    BOARD_CARD = "board_card"

    #: Writes an audit trail row but posts no board card.
    AUDIT_ONLY = "audit_only"

    ALL = (NONE, BOARD_CARD, AUDIT_ONLY)


class Failure:
    """Why a tool call did not succeed (ADR 0031 D2).

    Phase 1 only *classifies* — it never swallows. ``INTERNAL`` in particular
    must stay loud: LangChain's own guidance on ``wrap_tool_call`` error
    handling is explicit that runtime input errors are handled and
    implementation bugs bubble.
    """

    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    DENIED = "denied"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    CONFLICT = "conflict"
    INTERNAL = "internal"

    ALL = (
        NOT_FOUND,
        INVALID_INPUT,
        DENIED,
        UPSTREAM_UNAVAILABLE,
        CONFLICT,
        INTERNAL,
    )


class ToolOutcome:
    """The observed result of one tool call. Written to ``DeepRunLog.status``."""

    SUCCESS = "success"
    FAILURE = "failure"

    ALL = (SUCCESS, FAILURE)


class RunOutcome:
    """What one agent turn achieved, given how its tool calls went (D2).

    Three states, because two cannot express the common case honestly:

    ``COMPLETED``
        No tool call failed. The overwhelming majority of turns, and the only
        one that may claim a clean success.
    ``PARTIAL``
        Some tool calls failed and some succeeded. The turn still produced a
        usable answer, so discarding it would be its own kind of dishonesty —
        but calling it ``completed`` is the lie D2 exists to remove.
    ``FAILED``
        Tool calls were made and every one of them failed. This is the
        LLM-provider-outage shape: the model narrates "reviewed; no confident
        fix" over a stack of dead tool calls. There is no success here to
        protect.

    A turn that called no tools at all is ``COMPLETED`` — there is no tool
    evidence either way, and inventing a failure from silence would be the
    mirror-image defect.
    """

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"

    ALL = (COMPLETED, PARTIAL, FAILED)


def resolve_run_outcome(*, total_calls: int, failed_calls: int) -> str:
    """Classify a turn from its tool-call tally. See ``RunOutcome``."""
    if total_calls <= 0 or failed_calls <= 0:
        return RunOutcome.COMPLETED
    if failed_calls >= total_calls:
        return RunOutcome.FAILED
    return RunOutcome.PARTIAL


@dataclass(frozen=True)
class ToolSpec:
    """A tool's declaration. Every field is optional in Phase 1.

    ``ToolSpec()`` — the default every undeclared tool receives — carries
    nothing, asserts nothing, and changes nothing. See ``UNDECLARED``.
    """

    scope: str | None = None
    risk: str | None = None
    provenance: str | None = None
    failure_mode: str | None = None
    #: Finding ``source_type`` values this tool handles (ADR 0031 D6).
    handles: tuple[str, ...] = ()
    #: When the tool was introduced, and what replaces it (ADR 0031 D8).
    since: str | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        # Validate only what was actually supplied. An unset field is not a
        # declaration, so it cannot be an invalid one.
        if self.scope is not None and self.scope not in Scope.ALL:
            raise InvalidToolDeclarationError(f"ToolSpec.scope must be one of {Scope.ALL}, got {self.scope!r}")
        if self.provenance is not None and self.provenance not in Provenance.ALL:
            raise InvalidToolDeclarationError(
                f"ToolSpec.provenance must be one of {Provenance.ALL}, got {self.provenance!r}"
            )
        if self.failure_mode is not None and self.failure_mode not in Failure.ALL:
            raise InvalidToolDeclarationError(
                f"ToolSpec.failure_mode must be one of {Failure.ALL}, got {self.failure_mode!r}"
            )
        if not isinstance(self.handles, tuple):
            raise InvalidToolDeclarationError(f"ToolSpec.handles must be a tuple, got {type(self.handles).__name__}")

    @property
    def is_declared(self) -> bool:
        """True when the author declared anything at all.

        Phase 1 uses this only to label observations — an undeclared tool is
        observed exactly like a declared one, it is just reported as such so
        the F1 rollout in Phase 3 can be sized from real data.
        """
        return any(
            (
                self.scope,
                self.risk,
                self.provenance,
                self.failure_mode,
                self.handles,
                self.since,
                self.superseded_by,
            )
        )

    @property
    def is_complete(self) -> bool:
        """True when the four F1-required fields are all present (ADR 0031 F1)."""
        return all((self.scope, self.risk, self.provenance, self.failure_mode))

    def missing_required_fields(self) -> tuple[str, ...]:
        """The F1-required fields this spec does not carry."""
        return tuple(name for name in ("scope", "risk", "provenance", "failure_mode") if not getattr(self, name))

    def as_log_fields(self) -> dict[str, Any]:
        """The subset worth putting on an observation row. Omits empties."""
        fields: dict[str, Any] = {}
        if self.scope:
            fields["scope"] = self.scope
        if self.provenance:
            fields["provenance"] = self.provenance
        if self.handles:
            fields["handles"] = list(self.handles)
        return fields


#: The spec every tool that declares nothing receives. Shared singleton so an
#: identity check is a valid "this tool is undeclared" test.
UNDECLARED = ToolSpec()


def build_tool_spec(
    *,
    scope: str | None = None,
    risk: str | None = None,
    provenance: str | None = None,
    failure_mode: str | None = None,
    handles: tuple[str, ...] | list[str] | None = None,
    since: str | None = None,
    superseded_by: str | None = None,
) -> ToolSpec:
    """Build a ``ToolSpec`` from ``@tool(...)`` keyword arguments.

    Returns the shared ``UNDECLARED`` singleton when nothing was declared, so
    the overwhelmingly common "no declaration" case allocates nothing and is
    identity-comparable.
    """
    normalized_handles = tuple(handles) if handles else ()
    if not any((scope, risk, provenance, failure_mode, normalized_handles, since, superseded_by)):
        return UNDECLARED
    return ToolSpec(
        scope=scope,
        risk=risk,
        provenance=provenance,
        failure_mode=failure_mode,
        handles=normalized_handles,
        since=since,
        superseded_by=superseded_by,
    )


#: Prefix ``ToolResult.serialize()`` renders for a failed result.
#:
#: Phase 1 recovered the ``ok`` bit from this prefix because
#: ``_serialize_tool_result`` destroyed the structured result before any
#: middleware could see it. D2 replaced that with the artifact channel below, so
#: the prefix is now only the **last-resort** signal — it still catches the ~49
#: tools that hand-roll ``f"Error ...: {exc}"`` instead of returning a
#: ``ToolResult``, which is the population fitness function F4 exists to shrink.
TOOL_RESULT_ERROR_PREFIX = "Error:"


# ─────────────────────────────────────────────────────────────────────────────
# The outcome channel (ADR 0031 D2)
#
# A tool's return is flattened to a string before it becomes a ToolMessage — it
# has to be, because that string is what the model reads. The bit that was lost
# is carried instead on ``ToolMessage.artifact``, which LangChain documents as
# "additional data not sent to the model but can be accessed programmatically".
#
# That is the whole trick, and it is why the model-visible bytes do not move:
# the outcome never enters ``content``. It is also not a parallel channel
# invented for autosec — it is the framework's own out-of-band slot, which
# ``langchain_mcp_adapters`` uses for exactly the same purpose (structured
# content alongside the human-readable text).
# ─────────────────────────────────────────────────────────────────────────────

#: Namespaced so a tool that one day carries its own artifact cannot collide
#: with the outcome envelope, and so an unrelated artifact is never misread as
#: an outcome.
TOOL_OUTCOME_ARTIFACT_KEY = "autosec_tool_outcome"


@dataclass(frozen=True)
class ToolOutcomeEnvelope:
    """The structured outcome of one tool call, carried out-of-band.

    ``expected`` is the honesty flag: True when the tool *reported* this outcome
    (it returned a structured failure, or its declaration named the reason),
    False when the framework *inferred* it (an escaped exception, or an
    ``"Error: "`` prefix on a hand-rolled string). Collapsing the two is how
    "the tool told us it found nothing" became indistinguishable from "the tool
    blew up", which is the ambiguity D2 removes.
    """

    outcome: str
    failure: str | None = None
    retriable: bool = False
    expected: bool = False

    def as_artifact(self) -> dict[str, Any]:
        return {
            TOOL_OUTCOME_ARTIFACT_KEY: {
                "outcome": self.outcome,
                "failure": self.failure,
                "retriable": self.retriable,
                "expected": self.expected,
            }
        }


#: The envelope a tool that says nothing about its outcome gets. Shared
#: singleton: the overwhelmingly common case allocates nothing.
SUCCESS_ENVELOPE = ToolOutcomeEnvelope(outcome=ToolOutcome.SUCCESS)


def read_outcome_artifact(artifact: Any) -> ToolOutcomeEnvelope | None:
    """Recover the envelope from a ``ToolMessage.artifact``, or ``None``.

    Tolerant on purpose — a malformed or foreign artifact means "no outcome was
    carried", never an exception. The caller then falls back to the last-resort
    signals, which is exactly the pre-D2 behaviour.
    """
    if not isinstance(artifact, dict):
        return None
    payload = artifact.get(TOOL_OUTCOME_ARTIFACT_KEY)
    if not isinstance(payload, dict):
        return None
    outcome = payload.get("outcome")
    if outcome not in ToolOutcome.ALL:
        return None
    failure = payload.get("failure")
    return ToolOutcomeEnvelope(
        outcome=outcome,
        failure=failure if failure in Failure.ALL else None,
        retriable=bool(payload.get("retriable")),
        expected=bool(payload.get("expected")),
    )


def classify_tool_result(*, ok: bool, failure: str | None, retriable: bool, declared_failure_mode: str | None):
    """Build the envelope for a tool that returned a structured result.

    Precedence for the reason, and the reason for the precedence:

    1. what the **call** reported (``ToolResult(failure=...)``) — the tool knew;
    2. what the **tool declared** (``@tool(failure_mode=...)``) — D2's "a tool
       declares its failure semantics"; a tool whose only failure mode is an
       upstream outage should not have that outage recorded as ``INTERNAL``;
    3. ``INTERNAL`` — we genuinely do not know, and ``INTERNAL`` is the loud tier.

    Returns ``ToolOutcomeEnvelope``.
    """
    if ok:
        return SUCCESS_ENVELOPE
    reason = failure if failure in Failure.ALL else None
    if reason is None and declared_failure_mode in Failure.ALL:
        reason = declared_failure_mode
    return ToolOutcomeEnvelope(
        outcome=ToolOutcome.FAILURE,
        failure=reason or Failure.INTERNAL,
        retriable=bool(retriable),
        # The tool returned a structured result, so this outcome is reported
        # rather than inferred — regardless of whether it named a reason.
        expected=True,
    )


def classify_exception(exc: BaseException) -> str:
    """Map an exception that escaped a tool body onto a ``Failure`` value.

    Deliberately conservative: anything not recognised is ``INTERNAL``, which is
    the loud tier. This classifies; it never decides whether to swallow.
    """
    name = type(exc).__name__
    if name in {"DoesNotExist", "ObjectDoesNotExist", "Http404", "NotFound"}:
        return Failure.NOT_FOUND
    if name in {"ValidationError", "ValueError", "TypeError", "KeyError"}:
        return Failure.INVALID_INPUT
    if name in {"PermissionDenied", "NotAuthenticated", "PermissionError"}:
        return Failure.DENIED
    if name in {"IntegrityError", "ConflictError"}:
        return Failure.CONFLICT
    if name in {
        "ConnectionError",
        "Timeout",
        "ReadTimeout",
        "ConnectTimeout",
        "ChunkedEncodingError",
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        "ServiceUnavailable",
        "OperationalError",
    }:
        return Failure.UPSTREAM_UNAVAILABLE
    return Failure.INTERNAL


@dataclass(frozen=True)
class ToolCallObservation:
    """One observed tool call. Recorded by the governance middleware.

    Carries no tool input and no tool output — those already ride on the
    ``tool_observation`` payload, and duplicating them here would double the
    PII surface for no gain. This is the *outcome* record.
    """

    tool_name: str
    tool_call_id: str
    outcome: str
    latency_ms: int
    failure: str | None = None
    declared: bool = False
    spec_fields: dict[str, Any] = field(default_factory=dict)
    #: True when the tool reported this failure; False when we inferred it.
    #: See ``ToolOutcomeEnvelope.expected``.
    expected: bool = False
    retriable: bool = False

    @property
    def failed(self) -> bool:
        return self.outcome == ToolOutcome.FAILURE

    def as_payload(self) -> dict[str, Any]:
        """The governance block appended to a ``tool_observation`` payload."""
        payload: dict[str, Any] = {
            "outcome": self.outcome,
            "latency_ms": self.latency_ms,
            "declared": self.declared,
        }
        if self.failure:
            payload["failure"] = self.failure
            payload["expected"] = self.expected
            payload["retriable"] = self.retriable
        if self.spec_fields:
            payload.update(self.spec_fields)
        return payload
