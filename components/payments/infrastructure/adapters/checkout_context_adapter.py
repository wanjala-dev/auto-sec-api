from __future__ import annotations

from typing import Any

from components.payments.application.ports.checkout_context_port import CheckoutContextPort


class CheckoutContextAdapter(CheckoutContextPort):
    """Adapter that resolves checkout context using ORM models.

    Encapsulates all ORM-related queries for resolving team and user information,
    keeping this infrastructure logic out of the application service.
    """

    def resolve_checkout_context(
        self,
        *,
        workspace: Any,
        team_id: str | None = None,
        user_id: str | None = None,
    ) -> tuple[Any | None, str | None, str | None]:
        """Resolve team, customer email, and customer name for checkout.

        Performs ORM queries to look up team and user information, extracting
        the relevant details needed for payment processing.

        Args:
            workspace: The workspace entity
            team_id: Optional team ID to look up
            user_id: Optional user ID to resolve customer details from

        Returns:
            A tuple of (team, customer_email, customer_name)

        Raises:
            ValueError: If team or user is not found or invalid
        """
        from infrastructure.persistence.team.models import Team
        from infrastructure.persistence.users.models import CustomUser, UserProfile

        team = None
        if team_id:
            team = Team.objects.filter(
                id=team_id,
                workspace=workspace,
                status=Team.ACTIVE,
            ).first()
            if not team:
                raise ValueError("Team not found.")

        # Resolve user profile and extract customer details
        customer_email = None
        customer_name = None
        if user_id:
            user = CustomUser.objects.filter(id=user_id).first()
            if not user:
                raise ValueError("User not found.")
            customer_email = user.email

            # The display name lives on ``UserProfile.name`` — NOT
            # ``first_name``/``last_name`` (those exist on the auth user,
            # not the profile). Fall back to the auth user's full name and
            # finally the username so a missing or nameless profile never
            # blocks checkout. (We intentionally do NOT wrap this in a
            # broad ``except Exception`` — an unexpected error must surface
            # loudly, not be masked as a generic 400.)
            profile = UserProfile.objects.filter(user=user).first()
            customer_name = (getattr(profile, "name", "") or "").strip()
            if not customer_name:
                customer_name = (user.get_full_name() or "").strip() or user.username

        return team, customer_email, customer_name
