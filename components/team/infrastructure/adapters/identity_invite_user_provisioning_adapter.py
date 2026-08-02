"""Adapter: provision the invited user via ``identity``'s application surface.

Implements the team-owned :class:`InviteUserProvisioningPort` by delegating to
``identity``'s ``ProvisionInvitedUserUseCase`` (built by ``IdentityProvider``) — a
permitted cross-context call into another context's application layer, never its
persistence. ``identity`` owns the ``CustomUser``/``UserProfile`` write; the team
context only asks for it (architecture-manifesto Rule 2 / architecture-skill C2).
"""

from __future__ import annotations

from components.team.application.ports.invite_user_provisioning_port import (
    InvitedUserProbe,
    InviteUserProvisioningPort,
    ProvisionedUser,
)


class IdentityInviteUserProvisioningAdapter(InviteUserProvisioningPort):
    def probe(self, *, email: str) -> InvitedUserProbe:
        from components.identity.application.providers.identity_provider import (
            IdentityProvider,
        )

        use_case = IdentityProvider.build_provision_invited_user_use_case()
        probe = use_case.probe_established_user(email=email)
        return InvitedUserProbe(exists=probe.exists, established=probe.established)

    def provision_for_create(
        self,
        *,
        email: str,
        seed_is_contributor: bool,
        display_name: str,
        photo_url: str,
    ) -> ProvisionedUser:
        from components.identity.application.commands.invited_user_provisioning import (
            ProvisionInvitedUserCommand,
        )
        from components.identity.application.providers.identity_provider import (
            IdentityProvider,
        )

        use_case = IdentityProvider.build_provision_invited_user_use_case()
        result = use_case.execute(
            command=ProvisionInvitedUserCommand(
                purpose="create",
                email=email,
                seed_is_contributor=seed_is_contributor,
                display_name=display_name,
                photo_url=photo_url,
            )
        )
        return ProvisionedUser(
            user_id=result.user_id,
            email=result.email,
            created=result.created,
            established=result.established,
        )

    def provision_for_accept(
        self,
        *,
        email: str,
        seed_is_contributor: bool,
        password: str,
        first_name: str | None,
        last_name: str | None,
        active_workspace_id: str,
        active_team_id: str | None,
    ) -> ProvisionedUser:
        from components.identity.application.commands.invited_user_provisioning import (
            ProvisionInvitedUserCommand,
        )
        from components.identity.application.providers.identity_provider import (
            IdentityProvider,
        )

        use_case = IdentityProvider.build_provision_invited_user_use_case()
        result = use_case.execute(
            command=ProvisionInvitedUserCommand(
                purpose="accept",
                email=email,
                seed_is_contributor=seed_is_contributor,
                password=password,
                first_name=first_name,
                last_name=last_name,
                active_workspace_id=active_workspace_id,
                active_team_id=active_team_id,
            )
        )
        return ProvisionedUser(
            user_id=result.user_id,
            email=result.email,
            created=result.created,
            established=result.established,
        )

    def promote_contributor(self, *, user_id: str) -> None:
        from components.identity.application.providers.identity_provider import (
            IdentityProvider,
        )

        use_case = IdentityProvider.build_provision_invited_user_use_case()
        use_case.promote_contributor(user_id=user_id)
