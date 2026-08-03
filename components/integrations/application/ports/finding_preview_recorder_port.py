"""Port: record a fix-preview onto the finding it proposes to fix (ADR 0012 P6).

The preview (proposed patch + grounding provenance) is ``project.Task`` data. The
integrations context does not own that data, so it does not write it directly
(architecture-manifesto Rule 2 / architecture-skill C2). The preview use case depends
on this port; the adapter delegates to ``project``'s application surface, which
performs the actual Task write — mirroring :class:`FindingPrRecorderPort`.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc


class FindingPreviewRecorderPort(abc.ABC):
    @abc.abstractmethod
    def record_preview(
        self,
        *,
        workspace_id: str,
        task_id: str,
        performed_by: str,
        acting_agent: str,
        path: str,
        code: str,
        language: str,
        change_summary: str,
        grounding: tuple[dict, ...],
    ) -> None:
        """Stamp a proposed-fix preview onto the finding's board card (provenance +
        comment + ``payload.proposed_patch``). Never opens a PR. Idempotent-safe and a
        no-op if the task was deleted or already carries a draft PR — never raises."""
        ...
