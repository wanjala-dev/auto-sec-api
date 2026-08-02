"""Port: read the NON-SECRET GitHub credential surface for AI governance.

The ``integrations`` context owns :class:`GitHubConnection` (the workspace-scoped
GitHub PAT the triage agent uses to open draft PRs). The AI-governance report
(``components.agents.application.services.ai_governance_service``) needs to
*inventory* that credential surface — how many connections, their status, their
repo-allowlist, and whether a token is present — WITHOUT ever touching the token
material.

**Secret hazard — the reason this port exists.** ``GitHubConnection`` stores an
encrypted PAT in ``token_ciphertext``. That ciphertext MUST NOT cross this port's
boundary. The adapter reduces it to a **presence boolean** (``has_token``)
*inside* the adapter, before returning; the DTO below carries no token field, so
the ciphertext is structurally unreachable from any consumer. The token is never
returned and never logged (``.claude/rules/logging.md`` §4).

This is the same sanctioned inbound-read seam pattern as ``FindingFactsPort`` /
``TaskLookupPort``: the owning context defines a narrow port shaped to the
consumer's need, and an infrastructure adapter reads the owning context's ORM.

No Django imports — depends only on the standard library.

.. note::
   ``GitHubConnection`` is **deprecated by ADR 0010** in favour of the
   provider-tagged, multi-provider :class:`VcsConnection`. This port preserves the
   governance report's *current* behaviour (it inventories ``GitHubConnection``
   rows exactly as the inline code did). Migrating the credential inventory onto
   ``VcsConnection`` is a follow-up (it changes which rows are reported) and is
   deliberately out of scope for the ORM-burndown read routing done here.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class GitHubConnectionStatus:
    """The non-secret status of one ``GitHubConnection`` for the credential inventory.

    Carries exactly the fields ``compute_credential_inventory`` reports:
    identity + status, the repo-allowlist (the consent boundary), the token
    *presence* boolean (NEVER the token), and the lifecycle timestamps. There is
    deliberately **no token / ciphertext field** on this DTO — presence is all the
    report ever sees.
    """

    id: str
    name: str
    status: str
    repo_allowlist: list[str] = field(default_factory=list)
    # Reduced from ``token_ciphertext`` to a presence boolean INSIDE the adapter —
    # the ciphertext never travels this far and is never logged.
    has_token: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_used_at: datetime | None = None


class GitHubConnectionStatusReadPort(abc.ABC):
    @abc.abstractmethod
    def list_statuses(self, *, workspace_id: str) -> list[GitHubConnectionStatus]:
        """Return the non-secret status of every ``GitHubConnection`` in the workspace.

        Workspace-scoped (tenant isolation); ordered most-recent-first, matching the
        prior inline read. Each row's encrypted token is reduced to ``has_token`` in
        the adapter before this method returns — no secret material is exposed.
        """
        ...
