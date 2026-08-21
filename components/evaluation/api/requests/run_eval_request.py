"""Input DTO for POST …/suites/<id>/runs/ (ADR 0033).

The body carries nothing today: the workspace comes from the URL (so a
permission class can guard it — the lesson of #450) and the model comes from
the workspace's own AI config rather than the caller, so a request cannot ask
for an expensive model the workspace did not choose.

The DTO exists anyway, and is not ceremony: it is where an override would land
if one is ever added, and it keeps that decision in one reviewable place
instead of appearing as a stray `request.data.get(...)` in the controller.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunEvalRequest:
    workspace_id: str
    suite_id: str

    @classmethod
    def from_request(cls, request, *, workspace_id, suite_id) -> "RunEvalRequest":
        return cls(workspace_id=str(workspace_id), suite_id=str(suite_id))
