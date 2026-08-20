"""ADR 0031 D1 / Phase 3 — the model may never supply a tool's tenant.

This module is the single definition of *what counts as a tenancy key* and the
single mechanism for taking one away from a tool call. Both the framework
(`base.py`'s promotion loop, the governance middleware) and the fitness function
`tests/architecture/test_tool_payload_tenancy.py` read it, so there is one list
rather than three that drift.

── Why a scrub and not "drop the parameter from the schema" ──────────────────

D1's by-construction half is "the workspace id reaches the tool through the
runtime, not through its args schema". For a tool with a typed schema that is
literally true: leave the field out and the model cannot write it.

Nearly every tool in this codebase is not that shape. The legacy tools take a
single ``input_str`` and are promoted with ``LegacyStringToolInput``, whose
``model_config = ConfigDict(extra="allow")`` exists precisely so the model can
pass arbitrary keyword arguments — ``_adapt_legacy_tool`` then JSON-encodes them
into the payload the body parses. Under that schema there is no field to remove:
``workspace_id`` is an *extra*, and extras are allowed by design.

So the equivalent construction for this codebase is to delete the value rather
than the field. A tenancy key the framework strips before the body runs is a
tenancy key the body cannot read, whatever it was written to do — which is the
same guarantee, obtained where this codebase's tools actually live.

The tenant itself is never in doubt: it is ``agent.workspace_id``, bound when
the run is created from the authenticated request, and unreachable by the model.

── Two seams, deliberately ───────────────────────────────────────────────────

1. ``ToolGovernanceMiddleware`` — wraps the ``ToolNode``, so it sees every tool
   call on every agent regardless of how the tool was registered (D3 item 3).
   This is the one that covers the live LLM path.
2. ``_tenancy_scoped`` in the promotion loop — covers direct invocation, which
   is what the tool tests, the scripted ``AgentTestCase`` executor, and any
   future non-graph caller use. Middleware alone would leave those uncovered,
   and those are exactly where a regression would be written.

Belt and braces on purpose: the seams cost a dict comprehension per call and
each covers a path the other does not.
"""

from __future__ import annotations

import json
from typing import Any

#: Payload keys that carry a tenant identity. A tool that reads one of these out
#: of its own arguments is taking its tenant from the model.
#:
#: Broader than the two keys the tool bodies happened to read, because the point
#: is to make the *class* of bug impossible rather than the instances of it that
#: exist today. ``organization`` is included because this fork's workspace is
#: called an "organization" in the workspace agent's own surface, and ``org_id``
#: / ``tenant_id`` because they are the names a future author would reach for.
TENANCY_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "workspace_id",
        "workspace",
        "organization_id",
        "organization",
        "org_id",
        "tenant_id",
    }
)

#: The subset the fitness function scans tool bodies for. Narrower than the
#: scrub list because ``organization``/``workspace`` are ordinary English words
#: that appear as dict keys for non-tenancy reasons (a workspace *name*, an
#: organization *story*), and flagging those would bury the real violations.
TENANCY_SOURCE_KEYS: frozenset[str] = frozenset({"workspace_id", "organization_id"})


def scrub_tenancy_keys(args: Any) -> tuple[Any, tuple[str, ...]]:
    """Remove every tenancy key from a tool's arguments.

    Returns ``(scrubbed_args, removed_key_names)``. ``removed_key_names`` is
    ordered and exists so the caller can log the attempt — a model naming a
    workspace is worth seeing in the log stream even though nothing acts on it.

    Handles the three shapes a tool's arguments arrive in:

    - a ``dict`` of keyword arguments (the tool-calling path, and the middleware's
      ``tool_call["args"]``);
    - a JSON object encoded as a string (what ``_adapt_legacy_tool`` produces and
      what ``_coerce_payload`` parses back);
    - anything else — a plain string, ``None`` — returned untouched, because
      there is no key to remove.

    Never raises. A malformed payload is not this function's problem to report;
    the tool body's own coercion already handles it, and a scrub that could throw
    would turn a tenancy guard into an availability bug.
    """
    if isinstance(args, dict):
        removed = tuple(key for key in args if key in TENANCY_PAYLOAD_KEYS)
        if not removed:
            return args, ()
        return {key: value for key, value in args.items() if key not in TENANCY_PAYLOAD_KEYS}, removed

    if isinstance(args, str):
        stripped = args.strip()
        # Only a JSON *object* can carry keys. A bare string, a JSON array, or a
        # JSON scalar has nothing to scrub, and re-encoding them would change
        # what the tool body sees for no benefit.
        if not stripped.startswith("{"):
            return args, ()
        try:
            decoded = json.loads(stripped)
        except (ValueError, TypeError):
            return args, ()
        if not isinstance(decoded, dict):
            return args, ()
        scrubbed, removed = scrub_tenancy_keys(decoded)
        if not removed:
            return args, ()
        return json.dumps(scrubbed), removed

    return args, ()
