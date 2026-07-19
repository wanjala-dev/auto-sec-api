from __future__ import annotations

from typing import Any, Protocol


class CheckoutContextPort(Protocol):
    """Port for resolving checkout context (team, email, name) from workspace/user data.

    Abstracts ORM queries and user lookup logic away from the application service,
    keeping the service focused on business logic rather than infrastructure details.
    """

    def resolve_checkout_context(
        self,
        *,
        workspace: Any,
        team_id: str | None = None,
        user_id: str | None = None,
    ) -> tuple[Any | None, str | None, str | None]:
        """Resolve team, customer email, and customer name for checkout.

        Args:
            workspace: The workspace entity
            team_id: Optional team ID to look up
            user_id: Optional user ID to resolve customer details from

        Returns:
            A tuple of (team, customer_email, customer_name)

        Raises:
            ValueError: If team or user is not found or invalid
        """
        ...
