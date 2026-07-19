"""Port: look up the User model / instances without importing Django auth.

Application code that needs the User class or a user by id consumes
this port instead of ``django.contrib.auth.get_user_model``.
"""

from __future__ import annotations

from typing import Any, Protocol


class UserLookupPort(Protocol):
    def find_by_id(self, user_id: Any) -> Any | None:
        """Return the User row for ``user_id`` or ``None``."""
        ...
