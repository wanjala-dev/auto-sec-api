"""Engine-output integrity — the ONE place a scan's raw result document is validated.

Every engine we drive (Prowler, Trivy, Opengrep) returns its result as a **single
self-delimiting JSON document**: Prowler a top-level OCSF *array*, Trivy and Opengrep a
top-level envelope *object*. That property is the completeness signal this module relies
on — a document that was cut short (pod-log rotation, an OOM mid-write, a half-flushed
file) **cannot parse**. So "did it parse?" is not a convenience check, it is how we tell a
complete scan from a mutilated one.

WHY THIS EXISTS (the bug class it closes): each adapter used to parse its own stdout
"defensively" and return ``[]`` / ``{}`` when the JSON was bad. Combined with an exit
code of 0 — which a truncated-but-successful engine run genuinely has — that produced a
**COMPLETED ScanRun with zero findings**: a mutilated scan of a customer's account
reported as a clean one. For a security product that is the worst possible failure, and
it scales the wrong way (the bigger the account, the more output, the likelier the cut).
The defensiveness was pointed at the wrong risk: crashing the pipeline is recoverable and
visible; silently under-reporting is neither.

The rule this module enforces: **unusable output is a FAILED scan, never an empty one.**
Raising ``IncompleteScanOutputError`` (a ``ScanExecutionError``) propagates to
``run_scan_and_ingest``, which marks the ``ScanRun`` FAILED with an honest error and
re-raises — the same loud path an engine crash already takes.

What this deliberately does NOT do: it validates the *document*, not the *records*. A
genuinely clean scan (Prowler's ``[]``, a Trivy envelope with no vulnerabilities) parses
fine and completes normally — absence of findings is a real, reportable answer. And
individual malformed records inside a well-formed document stay the normalizers' lenient
business; one weird record must not fail a whole scan.

Pure domain logic: no Django, no engine SDK, no IO.
"""

from __future__ import annotations

import json

from components.scanning.domain.errors import IncompleteScanOutputError

# How much of the output's head/tail to quote in the error. Enough to diagnose (is this an
# error transcript? a truncated array?) without pasting megabytes of a customer's scan
# into an exception string, a log line, or the ScanRun.error column.
_SNIPPET_CHARS = 160

# The closing delimiter a complete document of each top-level shape must end with.
_CLOSERS = {"[": "]", "{": "}"}


def parse_engine_result_document(stdout: str | None, *, engine: str) -> dict | list:
    """Parse an engine's raw result document, or raise ``IncompleteScanOutputError``.

    Returns the decoded top-level ``dict`` or ``list``. Callers keep their own
    *shape* tolerance (envelope vs. bare payload) — this only guarantees the bytes
    were a complete, well-formed JSON document.

    Fails loud on the three ways output arrives unusable:

    1. **Nothing at all.** Every engine's Job script always emits its document — an
       empty stdout means the file was never written or the log was never retrieved,
       never that the target was clean (a clean Prowler scan still prints ``[]``).
    2. **Not parseable.** Truncation and corruption both land here; the diagnosis
       goes into the error so an operator sees *why*, not just *that*.
    3. **Not a JSON container.** A bare scalar (``null``, a number, a stray error
       line that happens to be valid JSON) is not a result document.
    """
    text = (stdout or "").strip()
    if not text:
        raise IncompleteScanOutputError(
            f"{engine} produced no output — the engine wrote no result document, or it could "
            f"not be retrieved. Treated as a FAILED scan, not a clean one."
        )

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise IncompleteScanOutputError(
            f"{engine} output is not a complete JSON document "
            f"({_describe_integrity(text)}): {exc}. "
            f"head={text[:_SNIPPET_CHARS]!r} tail={text[-_SNIPPET_CHARS:]!r}"
        ) from exc

    if not isinstance(data, dict | list):
        raise IncompleteScanOutputError(
            f"{engine} output parsed but is {type(data).__name__}, not a JSON object or array "
            f"— not a result document. head={text[:_SNIPPET_CHARS]!r}"
        )
    return data


def _describe_integrity(text: str) -> str:
    """A short, honest diagnosis of *how* the document is malformed.

    The high-signal case is truncation: the payload opens like a real result document
    but never closes. That is the pod-log-rotation / cut-short-write fingerprint, and
    naming it in the error is the difference between an operator seeing "bad JSON" and
    seeing "your scan output was cut off at 10.0 MiB".
    """
    size = len(text.encode("utf-8"))
    human = f"{size / (1024 * 1024):.2f} MiB" if size >= 1024 * 1024 else f"{size} bytes"
    expected_closer = _CLOSERS.get(text[:1])
    if expected_closer and not text.endswith(expected_closer):
        return (
            f"{human}, opens with {text[:1]!r} but never closes with {expected_closer!r} "
            f"— the output was TRUNCATED (log rotation / cut-short write), not merely invalid"
        )
    return f"{human}, malformed"
