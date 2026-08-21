"""Turn authored cases into a suite (ADR 0033 D14).

ONE path for both inputs. A typed form and an uploaded file are two ways of
producing the same list of rows, and they go through the same parse, the same
validation, the same duplicate collapse, and the same provenance. Two code paths
would be two sets of rules, and the second one to be written would be the one
missing a check.

What this service refuses to do is the interesting part, and each refusal is
there because the permissive version produces a number that lies:

**A partially-valid file does not become a partial suite.** Errors are returned
per row and nothing is written. Importing 47 of 50 leaves a suite that silently
differs from the file that made it.

**Duplicates are collapsed and counted.** The same lesson the miner learned when
1,645 rows turned out to be one decision: a pass rate is only as meaningful as
the number of distinct questions behind it.

**The suite is marked AUTHORED for ever.** That is what caps the claim tier at
DIRECTIONAL. A self-authored suite is a selection, not a sample — someone chose
which questions to ask — and no case count can turn a selection into evidence
that the agent is good in general.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.evaluation.domain.services import case_upload


@dataclass(frozen=True)
class AuthoredSuiteRequest:
    """What the operator asked for, from either the form or a file."""

    name: str
    agent_type: str
    axes: list[str]
    mode: str = "agent"
    system_prompt: str = ""
    forked_from_prompt_id: str = ""
    #: Raw file text (upload) — mutually exclusive with `rows`.
    raw: str = ""
    fmt: str = "json"
    #: Already-structured rows (the form) — mutually exclusive with `raw`.
    rows: list[dict] | None = None


@dataclass(frozen=True)
class AuthoredSuiteResult:
    suite_id: str | None
    accepted: int
    duplicates_collapsed: int
    errors: list[dict]

    @property
    def ok(self) -> bool:
        return self.suite_id is not None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "suite_id": self.suite_id,
            "accepted": self.accepted,
            "duplicates_collapsed": self.duplicates_collapsed,
            "errors": self.errors,
        }


class CaseAuthoringService:
    """Validates authored cases and persists them through a writer port."""

    def __init__(self, *, writer) -> None:
        self._writer = writer

    def create(self, *, workspace_id: str, request: AuthoredSuiteRequest) -> AuthoredSuiteResult:
        errors = _validate_request(request)
        if errors:
            return AuthoredSuiteResult(suite_id=None, accepted=0, duplicates_collapsed=0, errors=errors)

        if request.rows is not None:
            # The form hands over structured rows; serialising them to JSON just
            # to parse them back would be theatre, but they must still meet
            # exactly the same rules, so they go through the same validator.
            parsed = case_upload.parse(_as_json(request.rows), fmt="json")
        else:
            parsed = case_upload.parse(request.raw, fmt=request.fmt)

        if not parsed.ok:
            return AuthoredSuiteResult(
                suite_id=None,
                accepted=0,
                duplicates_collapsed=parsed.duplicates_collapsed,
                errors=[e.as_dict() for e in parsed.errors],
            )

        suite_id = self._writer.create_authored_suite(
            workspace_id=workspace_id,
            name=request.name.strip(),
            agent_type=request.agent_type.strip(),
            axes=list(request.axes),
            mode=request.mode,
            system_prompt=request.system_prompt,
            forked_from_prompt_id=request.forked_from_prompt_id,
            cases=parsed.cases,
        )

        return AuthoredSuiteResult(
            suite_id=str(suite_id),
            accepted=len(parsed.cases),
            duplicates_collapsed=parsed.duplicates_collapsed,
            errors=[],
        )


def _validate_request(request: AuthoredSuiteRequest) -> list[dict]:
    """Suite-level problems, addressed to the field that caused them.

    Row 0 means "the request, not a row" — the same convention the parser uses
    for whole-file errors.
    """
    errors: list[dict] = []

    if not (request.name or "").strip():
        errors.append({"row": 0, "message": "The suite needs a name."})
    if not (request.agent_type or "").strip():
        errors.append({"row": 0, "message": "Choose which agent this suite is for."})
    if not request.axes:
        errors.append({"row": 0, "message": "Choose at least one axis — an axis is what each case is graded on."})
    if request.mode not in ("agent", "prompt"):
        errors.append({"row": 0, "message": f"Unknown mode '{request.mode}'. Use agent or prompt."})
    if request.mode == "prompt" and not (request.system_prompt or "").strip():
        # The mode's whole purpose is to test a prompt. Accepting an empty one
        # would produce a run that grades nothing and reports it as a score.
        errors.append({"row": 0, "message": "Prompt mode needs a system prompt — it is the thing being tested."})
    if request.mode == "agent" and (request.system_prompt or "").strip():
        # Silently ignoring it would let someone believe they were testing their
        # edited prompt while the real agent's prompt was what actually ran.
        errors.append(
            {
                "row": 0,
                "message": (
                    "Agent mode runs the agent's own system prompt. To test a prompt you wrote, "
                    "switch this suite to prompt mode."
                ),
            }
        )
    if request.rows is None and not (request.raw or "").strip():
        errors.append({"row": 0, "message": "No cases were provided."})
    if request.rows is not None and request.raw:
        errors.append({"row": 0, "message": "Provide either typed cases or a file, not both."})

    return errors


def _as_json(rows: list[dict]) -> str:
    import json

    return json.dumps({"cases": rows}, default=str)


__all__ = ["AuthoredSuiteRequest", "AuthoredSuiteResult", "CaseAuthoringService"]
