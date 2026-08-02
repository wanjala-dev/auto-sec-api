"""Port: has the draft PR that carried a fix actually been MERGED? (ADR 0012 P4a)

The D1 entry-gate's "applied" leg was, in P3, an explicit operator claim — the
honest gap this port closes. The reconciler asks this port for the *verified*
merge fact so ``pr_applied`` is backed by the host's un-forgeable ``merged``
boolean, never a blind flag.

Shaped to the gate's need (a merged boolean + the canonical PR url), NOT to any
one host's API. The infrastructure adapter delegates to the ``integrations``
context's ``VcsPort`` (via its provider registry) — a permitted read-only use of
another context's *application* surface (architecture skill C3): remediation
never reads ``VcsConnection`` rows or decrypts tokens itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MergeStatus:
    """The verified merge fact for a finding's draft PR.

    ``checked`` distinguishes "we asked the host and it said not-merged"
    (``checked=True, merged=False``) from "we could not check" (no connection,
    an API error, an un-parseable ref → ``checked=False``). The reconciler only
    advances a finding when ``checked and merged`` — an unverifiable PR is left
    for the next cycle, never assumed applied (fail-closed)."""

    checked: bool
    merged: bool
    pr_url: str = ""
    detail: str = ""  # human-readable reason when not checked/merged (no secrets)


class PullRequestMergeCheckPort(ABC):
    @abstractmethod
    def check_merged(self, *, workspace_id: str, repo: str, pr_ref: str) -> MergeStatus:
        """Return the verified merge status of PR ``pr_ref`` in ``repo`` for a
        workspace. Never raises for an expected failure (no connection / API
        error) — those resolve to ``checked=False`` so the reconciler skips the
        finding this cycle rather than crashing the whole sweep."""
