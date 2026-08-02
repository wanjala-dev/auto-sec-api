"""Adapter: provision the invited user against the ``users`` ORM.

Implements :class:`InvitedUserStorePort`. This is the ONLY place the invited-user
provisioning touches ``CustomUser`` / ``UserProfile`` — the writes moved here
verbatim from the two team invite use cases, so the behaviour is byte-identical;
only their *home* changed to the context that owns the models.

Opens no transaction of its own — it runs inside the caller's ``atomic()`` so a
later failure in the invite flow rolls these writes back too.
"""

from __future__ import annotations

from components.identity.application.commands.invited_user_provisioning import (
    EstablishedUserProbe,
    ProvisionedInvitedUser,
    ProvisionInvitedUserCommand,
)
from components.identity.application.ports.invited_user_store_port import (
    InvitedUserStorePort,
)


class OrmInvitedUserProvisioningRepository(InvitedUserStorePort):
    def probe_established_user(self, *, email: str) -> EstablishedUserProbe:
        from infrastructure.persistence.users.models import CustomUser

        existing_user = CustomUser.objects.filter(email=email).first()
        established = existing_user is not None and existing_user.has_usable_password()
        return EstablishedUserProbe(exists=existing_user is not None, established=established)

    def promote_contributor(self, *, user_id: str) -> None:
        from infrastructure.persistence.users.models import CustomUser

        user = CustomUser.objects.filter(id=user_id).first()
        if user is not None and not user.is_contributor:
            user.is_contributor = True
            user.save(update_fields=["is_contributor"])

    def provision_invited_user(self, *, command: ProvisionInvitedUserCommand) -> ProvisionedInvitedUser:
        from infrastructure.persistence.users.models import CustomUser

        user, created = CustomUser.objects.get_or_create(
            email=command.email,
            defaults={
                "username": command.email,
                "is_active": True,
                # accept sets verified True; create leaves it False (unchanged
                # per-flow behaviour — see the branch below).
                "is_verified": command.purpose == "accept",
                "is_onboard_complete": True,
                "is_contributor": command.seed_is_contributor,
            },
        )

        if command.purpose == "create":
            return self._apply_create_flow(user=user, created=created, command=command)
        return self._apply_accept_flow(user=user, created=created, command=command)

    # ── create-invite flow ────────────────────────────────────────────────
    def _apply_create_flow(
        self, *, user, created: bool, command: ProvisionInvitedUserCommand
    ) -> ProvisionedInvitedUser:
        from infrastructure.persistence.users.models import UserProfile

        # Brand-new placeholders must have an unusable password so
        # has_usable_password() is a reliable "already has an account" signal.
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])

        # An "established" user is a pre-existing row with a usable password.
        established = (not created) and user.has_usable_password()

        user_dirty_fields = []
        display_name = (command.display_name or "").strip()
        if display_name:
            pieces = display_name.split(maxsplit=1)
            first = pieces[0]
            last = pieces[1] if len(pieces) > 1 else ""
            if not user.first_name:
                user.first_name = first
                user_dirty_fields.append("first_name")
            if last and not user.last_name:
                user.last_name = last
                user_dirty_fields.append("last_name")
        if user_dirty_fields:
            user.save(update_fields=user_dirty_fields)

        photo_url = (command.photo_url or "").strip()
        if photo_url:
            profile, _ = UserProfile.objects.get_or_create(user=user)
            if not profile.photo_url:
                profile.photo_url = photo_url[:120]
                profile.save(update_fields=["photo_url"])

        return ProvisionedInvitedUser(
            user_id=str(user.id),
            email=user.email,
            created=created,
            established=established,
        )

    # ── accept-invite flow ────────────────────────────────────────────────
    def _apply_accept_flow(
        self, *, user, created: bool, command: ProvisionInvitedUserCommand
    ) -> ProvisionedInvitedUser:
        from infrastructure.persistence.users.models import UserProfile

        if command.password:
            user.set_password(command.password)
        user.is_active = True
        user.is_verified = True
        user.is_onboard_complete = True
        # is_contributor promotion is a SEPARATE step (``promote_contributor``)
        # the caller runs only after the membership-preserve decision, matching
        # the original guard order.
        if command.first_name and not user.first_name:
            user.first_name = command.first_name.strip()
        if command.last_name and not user.last_name:
            user.last_name = command.last_name.strip()
        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        if command.active_workspace_id is not None:
            profile.active_workspace_id = command.active_workspace_id
        if command.active_team_id is not None:
            profile.active_team_id = command.active_team_id
        profile.save()

        return ProvisionedInvitedUser(
            user_id=str(user.id),
            email=user.email,
            created=created,
            established=False,
        )
