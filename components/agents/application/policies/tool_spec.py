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


#: Prefix ``ToolResult.serialize()`` renders for a failed result. The governance
#: middleware reads it to recover the ``ok`` bit that ``_serialize_tool_result``
#: flattens away before anything else can see it (ADR 0031 D2).
TOOL_RESULT_ERROR_PREFIX = "Error:"


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
        if self.spec_fields:
            payload.update(self.spec_fields)
        return payload
