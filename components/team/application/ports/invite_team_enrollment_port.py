"""Port (team-owned): enroll an invite acceptor into the invitation's team.

The persona-invite accept flow must, for team-attached personas (contributor /
volunteer), put the new member INTO the team the invitation targeted. The
original inline enrollment broke silently when ``TeamMembershipRepository`` was
renamed to ``OrmTeamMembershipRepository`` — the ImportError was swallowed by a
bare ``except Exception: pass``, so persona-invite team enrollment was a dead
no-op in production (issue #60). This port is the root fix: the framework-free
accept use case depends on this seam; the adapter delegates to the existing
``TeamMembershipPort`` machinery (no second enrollment implementation).

ID-based like the sibling accept-flow ports (``WorkspaceMembershipWritePort``),
so the application layer never touches model instances. No Django imports.
"""

from __future__ import annotations

import abc


class InviteTeamEnrollmentPort(abc.ABC):
    @abc.abstractmethod
    def enroll(
        self,
        *,
        user_id: str,
        workspace_id: str,
        team_id: str,
        mark_contributor: bool,
    ) -> bool:
        """Enroll ``user_id`` into ``team_id`` (team members + membership row +
        active-context update on the profile).

        Returns ``True`` when enrollment ran, ``False`` when the team or
        workspace no longer exists (an invite can outlive its team — the accept
        must still succeed; the miss is logged by the adapter). Genuine
        database/integrity errors propagate — never swallowed (#60's lesson).
        ``mark_contributor`` mirrors the accept flow's persona rule: only a
        contributor-persona invite may flip the global ``is_contributor`` flag.
        Runs inside the caller's ``atomic()``.
        """
        ...
