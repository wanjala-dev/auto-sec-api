"""Port: read the NON-SECRET VCS credential surface for AI governance.

The ``integrations`` context owns :class:`VcsConnection` (the workspace-scoped
VCS credential the triage agent uses to open draft PRs — a fine-grained PAT in
``pat`` mode, a GitHub App installation in ``github_app`` mode). The
AI-governance report (``components.agents.application.services.
ai_governance_service``) needs to *inventory* that credential surface — how many
connections, their provider + auth mode, their status, their repo-allowlist, and
whether a usable credential is present — WITHOUT ever touching secret material.

**Secret hazard — the reason this port exists.** ``VcsConnection`` stores an
encrypted PAT in ``token_ciphertext`` (PAT mode). That ciphertext MUST NOT cross
this port's boundary. The adapter reduces it to a **presence boolean**
(``has_token``) *inside* the adapter, before returning; the DTO below carries no
token field, so the ciphertext is structurally unreachable from any consumer.
App-mode rows store no secret at all — their short-lived installation tokens
live only in the Django cache, which this seam never reads. The
``installation_id`` IS carried: it is an opaque numeric id, useless without the
app's private key (the same reasoning as the REST resource). Nothing here is
ever logged (``.claude/rules/logging.md`` §4).

This is the same sanctioned inbound-read seam pattern as ``FindingFactsPort`` /
``TaskLookupPort``: the owning context defines a narrow port shaped to the
consumer's need, and an infrastructure adapter reads the owning context's ORM.

No Django imports — depends only on the standard library.

.. note::
   This port supersedes the ``GitHubConnectionStatusReadPort`` that inventoried
   the **deprecated** ``GitHubConnection`` model (ADR 0010). That left every
   ``VcsConnection`` — including all GitHub App installations — invisible to
   the governance inventory: a customer could install the App and governance
   would claim no GitHub credential existed. Migration 0008 copied all legacy
   rows into ``VcsConnection`` (ids preserved), so reading ``VcsConnection``
   alone is complete and never double-counts.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class VcsConnectionStatus:
    """The non-secret status of one ``VcsConnection`` for the credential inventory.

    Carries exactly the fields ``compute_credential_inventory`` reports: identity,
    provider + auth mode, status (with ``last_error`` so a revoked-on-GitHub row
    reads as such), the repo-allowlist (the consent boundary), the credential
    *presence* boolean and a human-readable non-secret ``credential`` label
    (NEVER the token), and the lifecycle timestamps. There is deliberately **no
    token / ciphertext field** on this DTO — presence is all the report ever sees.
    """

    id: str
    provider: str
    name: str
    status: str
    #: ``pat`` | ``github_app`` — how this connection obtains its runtime token.
    auth_mode: str
    #: The bound GitHub App installation (app mode only). NOT a secret: an opaque
    #: numeric id, useless without the app's private key.
    installation_id: int | None = None
    repo_allowlist: list[str] = field(default_factory=list)
    #: "Has a usable credential": a stored (encrypted) PAT, or an app installation
    #: that mints short-lived tokens on demand. Reduced INSIDE the adapter — no
    #: ciphertext travels this far and nothing is ever logged.
    has_token: bool = False
    #: Human-readable, secret-free description of the credential kind, e.g.
    #: ``"fine-grained PAT (encrypted)"`` / ``"GitHub App installation 4242"``.
    credential: str = ""
    #: Operational note stamped by verify / revocation sync (non-secret) — how a
    #: revoked-on-GitHub installation reads honestly in the inventory.
    last_error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_used_at: datetime | None = None


class VcsConnectionStatusReadPort(abc.ABC):
    @abc.abstractmethod
    def list_statuses(self, *, workspace_id: str) -> list[VcsConnectionStatus]:
        """Return the non-secret status of every ``VcsConnection`` in the workspace.

        All providers and both auth modes — every row is an AI-reachable
        credential the inventory must see. Workspace-scoped (tenant isolation);
        ordered most-recent-first. Each row's encrypted token is reduced to
        ``has_token`` in the adapter before this method returns — no secret
        material is exposed.
        """
        ...
