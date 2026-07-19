from __future__ import annotations

import threading
from contextlib import contextmanager


_state = threading.local()


def set_current_actor(user) -> None:
    """Persist the current request user for signal handlers."""
    _state.actor = user if getattr(user, 'is_authenticated', False) else None


def get_current_actor():
    """Return the active request user, if any."""
    return getattr(_state, 'actor', None)


@contextmanager
def override_current_actor(user):
    """Temporarily swap the active actor, useful for tests or scripts."""
    previous = get_current_actor()
    set_current_actor(user)
    try:
        yield
    finally:
        set_current_actor(previous)


class CurrentActorMiddleware:
    """Store ``request.user`` for use inside model signals."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_actor(getattr(request, 'user', None))
        try:
            response = self.get_response(request)
        finally:
            set_current_actor(None)
        return response
