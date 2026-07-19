"""Build the grounding corpus a newsletter's figures are checked against.

At send time a newsletter carries its generation-time financial metrics on
``content_payload['metrics']`` (donation totals, counts, top-donor amounts,
recipient counts, deltas, event counts). Those metrics ARE the ground truth
for the sent copy — the faithfulness verifier flags any numeric token in the
rendered body that isn't present in this corpus.

Pure domain logic — no framework imports.
"""

from __future__ import annotations

import datetime
from typing import Any


def has_grounding(metrics: dict | None) -> bool:
    """True when there is a metrics corpus to verify figures against.

    A newsletter with no persisted metrics (a purely hand-written ad-hoc
    send) has no ground truth, so the faithfulness gate does not apply —
    there is nothing to check the figures against.
    """
    return bool(metrics)


def build_grounding_texts(
    metrics: dict | None,
    *,
    period_start: datetime.date | None = None,
    period_end: datetime.date | None = None,
) -> list[str]:
    """Flatten persisted metrics + reporting period into a grounding corpus.

    Every legitimately-citable figure must surface as a string so the
    verifier reads it as grounded: donation totals, counts, donor amounts,
    recipient counts, deltas, event counts — plus the reporting period's
    dates so "September 2026" / "2026" are not flagged as fabricated.
    """
    texts: list[str] = []
    _flatten(metrics, texts)
    for boundary in (period_start, period_end):
        if boundary is not None:
            texts.append(boundary.isoformat())
            texts.append(str(boundary.year))
            texts.append(boundary.strftime("%B %Y"))
    return [text for text in texts if text]


def _flatten(value: Any, out: list[str]) -> None:
    """Recursively collect every scalar in a metrics structure as a string."""
    if value is None or isinstance(value, bool):
        # bool is an int subclass — exclude it so True/False don't become
        # numeric grounding tokens.
        return
    if isinstance(value, dict):
        for item in value.values():
            _flatten(item, out)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _flatten(item, out)
    else:
        out.append(str(value))
