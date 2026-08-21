"""Parse and validate a user-authored case file (ADR 0033 D14).

Framework-free on purpose: this is where a customer's file becomes cases, and
the rules it enforces are domain rules, not HTTP ones.

Three things it refuses to do, each of which is the easy implementation:

**It does not partially import.** A file with bad rows is REJECTED with a reason
per row, rather than importing the rows that parsed. Silently importing 47 of 50
leaves a suite whose size disagrees with what the operator uploaded and whose
missing three are invisible — and the next run scores against a dataset nobody
intended.

**It does not accept duplicates as variety.** A suite's pass rate is only as
meaningful as the number of DISTINCT questions in it, which is the same lesson
the miner learned from 1,645 rows collapsing to one decision. Duplicates are
collapsed and REPORTED, so someone pasting the same case 200 times is told what
they actually have.

**It does not invent structure.** A row missing a scenario is an error, not a
row with an empty scenario — because a case with no question is scored anyway
and contributes a verdict about nothing.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field

#: Ceiling on a single upload. Sized against the field's own guidance — 200-500
#: cases is a production golden set, 1000+ a mature one — so this is generous
#: rather than restrictive, while still bounding what one request can do.
MAX_CASES = 2000

#: Per-field ceilings. A case is a prompt, not a document; without these one
#: pasted log file becomes an agent prompt that costs real money to run.
MAX_SCENARIO_CHARS = 500
MAX_FIELD_CHARS = 20000
MAX_CRITERIA = 8
MAX_CRITERION_CHARS = 500

_WHITESPACE = re.compile(r"\s+")

#: The columns a CSV may carry. `prompt_inputs` may be a JSON object, or the
#: sheet can use plain columns and everything unrecognised is folded into the
#: inputs — spreadsheets are how non-engineers will actually build these.
_RESERVED_COLUMNS = {"scenario", "solution_criteria", "label", "source_ref", "prompt_inputs"}

_VALID_LABELS = {"good", "bad", "unlabelled"}


@dataclass(frozen=True)
class ParsedCase:
    """One case from a file, already validated."""

    scenario: str
    prompt_inputs: dict
    solution_criteria: list[str]
    label: str
    source_ref: str

    def dedupe_key(self) -> tuple:
        """What makes two uploaded cases the same QUESTION.

        Label and source_ref are excluded deliberately: relabelling the same
        scenario does not make it a second question, and source_ref is the
        author's own bookkeeping.
        """
        return (
            _normalise(self.scenario),
            json.dumps(self.prompt_inputs, sort_keys=True, separators=(",", ":"), default=str),
        )


@dataclass(frozen=True)
class RowError:
    """A rejected row, addressed the way the author sees their own file."""

    row: int
    message: str

    def as_dict(self) -> dict:
        return {"row": self.row, "message": self.message}


@dataclass(frozen=True)
class UploadParseResult:
    cases: list[ParsedCase] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    #: Rows dropped as duplicates of an earlier row in the SAME file.
    duplicates_collapsed: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.cases)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "accepted": len(self.cases),
            "duplicates_collapsed": self.duplicates_collapsed,
            "errors": [e.as_dict() for e in self.errors],
        }


def _normalise(value: str) -> str:
    return _WHITESPACE.sub(" ", (value or "").strip()).casefold()


def parse(raw: str, *, fmt: str) -> UploadParseResult:
    """Parse a JSON or CSV case file. Never raises on bad input."""
    fmt = (fmt or "").lower()
    if fmt == "json":
        rows, errors = _rows_from_json(raw)
    elif fmt == "csv":
        rows, errors = _rows_from_csv(raw)
    else:
        return UploadParseResult(errors=[RowError(row=0, message=f"Unsupported format '{fmt}'. Use json or csv.")])

    if errors:
        return UploadParseResult(errors=errors)
    if not rows:
        return UploadParseResult(errors=[RowError(row=0, message="The file contained no cases.")])
    if len(rows) > MAX_CASES:
        return UploadParseResult(
            errors=[
                RowError(
                    row=0,
                    message=f"{len(rows)} cases exceeds the {MAX_CASES}-case limit for one upload.",
                )
            ]
        )

    cases: list[ParsedCase] = []
    row_errors: list[RowError] = []
    seen: set[tuple] = set()
    duplicates = 0

    for index, row in enumerate(rows, start=1):
        case, error = _validate_row(row, index)
        if error is not None:
            row_errors.append(error)
            continue
        key = case.dedupe_key()
        if key in seen:
            # Not an error. A duplicate is a real thing people do, and the
            # honest response is to keep one and say how many were folded in —
            # not to reject the file, and not to pretend the suite is larger.
            duplicates += 1
            continue
        seen.add(key)
        cases.append(case)

    if row_errors:
        # All-or-nothing: see the module docstring. A partial import produces a
        # suite that silently differs from the file that created it.
        return UploadParseResult(errors=row_errors, duplicates_collapsed=duplicates)

    return UploadParseResult(cases=cases, duplicates_collapsed=duplicates)


def _rows_from_json(raw: str) -> tuple[list[dict], list[RowError]]:
    try:
        payload = json.loads(raw or "")
    except (ValueError, TypeError) as exc:
        return [], [RowError(row=0, message=f"The file is not valid JSON: {exc}")]

    # Accept both a bare list and {"cases": [...]} — the template emits the
    # latter, and people hand-write the former.
    if isinstance(payload, dict):
        payload = payload.get("cases")
    if not isinstance(payload, list):
        return [], [RowError(row=0, message='Expected a list of cases, or an object with a "cases" list.')]
    if any(not isinstance(item, dict) for item in payload):
        return [], [RowError(row=0, message="Every case must be an object with named fields.")]
    return payload, []


def _rows_from_csv(raw: str) -> tuple[list[dict], list[RowError]]:
    try:
        reader = csv.DictReader(io.StringIO(raw or ""))
        rows = list(reader)
    except (csv.Error, ValueError) as exc:
        return [], [RowError(row=0, message=f"The file is not valid CSV: {exc}")]

    if not reader.fieldnames:
        return [], [RowError(row=0, message="The CSV has no header row, so its columns cannot be identified.")]
    if "scenario" not in {(name or "").strip().lower() for name in reader.fieldnames}:
        return [], [RowError(row=0, message="The CSV needs a 'scenario' column — it is the question being asked.")]

    normalised: list[dict] = []
    for row in rows:
        item: dict = {}
        extras: dict = {}
        for key, value in row.items():
            name = (key or "").strip().lower()
            if not name:
                continue
            if name in _RESERVED_COLUMNS:
                item[name] = value
            else:
                # Unrecognised columns become prompt inputs rather than being
                # dropped. Dropping them silently would discard the very
                # context the author added the column to supply.
                extras[name] = value
        if extras:
            item.setdefault("prompt_inputs", {})
            if isinstance(item["prompt_inputs"], dict):
                item["prompt_inputs"].update(extras)
            else:
                item["_extras"] = extras
        normalised.append(item)
    return normalised, []


def _validate_row(row: dict, index: int) -> tuple[ParsedCase | None, RowError | None]:
    scenario = str(row.get("scenario") or "").strip()
    if not scenario:
        return None, RowError(row=index, message="'scenario' is required — it is the question this case asks.")
    if len(scenario) > MAX_SCENARIO_CHARS:
        return None, RowError(
            row=index,
            message=f"'scenario' is {len(scenario)} characters; the limit is {MAX_SCENARIO_CHARS}.",
        )

    inputs, error = _coerce_inputs(row, index)
    if error is not None:
        return None, error

    criteria, error = _coerce_criteria(row, index)
    if error is not None:
        return None, error

    label = str(row.get("label") or "unlabelled").strip().lower() or "unlabelled"
    if label not in _VALID_LABELS:
        return None, RowError(
            row=index,
            message=f"'label' must be one of {', '.join(sorted(_VALID_LABELS))} — got '{label}'.",
        )

    return (
        ParsedCase(
            scenario=scenario,
            prompt_inputs=inputs,
            solution_criteria=criteria,
            label=label,
            source_ref=str(row.get("source_ref") or "").strip()[:255],
        ),
        None,
    )


def _coerce_inputs(row: dict, index: int) -> tuple[dict, RowError | None]:
    raw = row.get("prompt_inputs")
    if raw in (None, ""):
        inputs: dict = {}
    elif isinstance(raw, dict):
        inputs = dict(raw)
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}, RowError(row=index, message="'prompt_inputs' must be a JSON object.")
        if not isinstance(parsed, dict):
            return {}, RowError(row=index, message="'prompt_inputs' must be a JSON object, not a list or value.")
        inputs = parsed
    else:
        return {}, RowError(row=index, message="'prompt_inputs' must be a JSON object.")

    extras = row.get("_extras")
    if isinstance(extras, dict):
        inputs.update(extras)

    flattened = {str(k): v for k, v in inputs.items() if str(k).strip()}
    for key, value in flattened.items():
        if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
            return {}, RowError(
                row=index,
                message=f"'{key}' is {len(value)} characters; the limit is {MAX_FIELD_CHARS}.",
            )
    return flattened, None


def _coerce_criteria(row: dict, index: int) -> tuple[list[str], RowError | None]:
    raw = row.get("solution_criteria")
    if raw in (None, ""):
        return [], None
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            values = decoded if isinstance(decoded, list) else [raw]
        except ValueError:
            # A plain string is a single criterion, and a semicolon-separated
            # list is what a spreadsheet produces. Both are what people mean.
            values = [part for part in raw.split(";")]
    elif isinstance(raw, list):
        values = raw
    else:
        return [], RowError(row=index, message="'solution_criteria' must be a list of short strings.")

    cleaned = [str(v).strip() for v in values if str(v).strip()]
    if len(cleaned) > MAX_CRITERIA:
        return [], RowError(
            row=index,
            message=f"{len(cleaned)} criteria; the limit is {MAX_CRITERIA}. Criteria are checks, not a specification.",
        )
    for value in cleaned:
        if len(value) > MAX_CRITERION_CHARS:
            return [], RowError(
                row=index,
                message=f"A criterion is {len(value)} characters; the limit is {MAX_CRITERION_CHARS}.",
            )
    return cleaned, None


TEMPLATE = {
    "cases": [
        {
            "scenario": "Public S3 bucket holding application logs",
            "prompt_inputs": {
                "title": "S3 bucket 'prod-app-logs' is publicly readable",
                "severity": "high",
                "asset_urn": "arn:aws:s3:::prod-app-logs",
            },
            "solution_criteria": [
                "Names the specific bucket",
                "Proposes a bucket policy or Block Public Access change",
            ],
            "label": "good",
            "source_ref": "your-ticket-123",
        },
        {
            "scenario": "Dependency CVE with no reachable call path",
            "prompt_inputs": {
                "title": "CVE-2024-0001 in transitive dependency",
                "severity": "medium",
                "file_path": "requirements/base.txt",
            },
            "solution_criteria": ["Notes the vulnerable code is not reachable", "Does not escalate severity"],
            "label": "good",
            "source_ref": "your-ticket-124",
        },
    ]
}


__all__ = [
    "MAX_CASES",
    "MAX_CRITERIA",
    "MAX_FIELD_CHARS",
    "MAX_SCENARIO_CHARS",
    "TEMPLATE",
    "ParsedCase",
    "RowError",
    "UploadParseResult",
    "parse",
]
