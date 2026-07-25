"""Declarative subscription registry for domain-event handlers (shared kernel).

Cross-context event wiring lives here, in the shared kernel, so that **no bounded
context couples to another in order to subscribe** — a context declares a handler
with ``@subscribes_to(EventClass)`` in its own ``application/handlers`` package, and
both emitter and subscriber depend only on the kernel (Graça, "Decoupling the
components"). Previously this lived in ``agents`` and any other context that wanted
to subscribe had to import from ``agents.application`` — that coupling is what this
relocation removes.

Public API:

* ``@subscribes_to(EventClass)`` — register a handler function for a domain event
  type. Stackable for handlers that react to multiple events.
* ``SubscriptionRegistry.bind_all(publisher, packages)`` — called once from the
  composition root at Django app ready(). Discovers the handler modules in
  ``packages`` (importing them fires the decorators), then subscribes each collected
  ``(event_type, handler)`` pair with the publisher. **The composition root owns the
  list of handler packages** — the kernel never names a context, keeping the
  dependency direction correct (nothing in the kernel points outward to a context).
* ``SubscriptionRegistry.entries`` — read-only view for tests + introspection.

Auto-discovery walks each package's ``*.py`` modules, skipping names starting with
``_`` (shared helpers, not handler entry points). Importing a module is what fires
its ``@subscribes_to`` decorators and populates the registry.

Idempotency: ``discover`` runs once (guarded by ``_discovered``); ``clear`` resets it
for tests.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Callable
from typing import Any

from components.shared_kernel.domain.events import DomainEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[DomainEvent], Any]


class SubscriptionRegistry:
    """Module-level registry of ``(event_type, handler)`` subscriptions.

    Populated at handler-module import time via ``@subscribes_to(...)`` and bound to
    the event publisher at Django app ready().
    """

    _entries: list[tuple[type[DomainEvent], EventHandler]] = []
    _discovered: bool = False

    @classmethod
    def register(cls, event_type: type[DomainEvent], handler: EventHandler) -> None:
        """Add a ``(event_type, handler)`` subscription.

        Called by ``@subscribes_to``; not normally called directly. Duplicates
        (same event type, same handler identity) are deduplicated — Python imports
        are cached so the decorator typically fires once per handler, but this guards
        against test paths that re-import.
        """
        entry = (event_type, handler)
        if entry in cls._entries:
            return
        cls._entries.append(entry)

    @classmethod
    def discover(cls, packages: tuple[str, ...] = ()) -> None:
        """Import every handler module under each package path in ``packages``.

        Importing fires ``@subscribes_to`` which populates the registry. Idempotent —
        the second call is a no-op via ``_discovered``. Modules whose names start with
        ``_`` are skipped (shared helpers, not handler entry points).
        """
        if cls._discovered:
            return
        cls._discovered = True

        for package_path in packages:
            try:
                handlers_pkg = importlib.import_module(package_path)
            except Exception:
                # A context without a handlers package (or a broken one) must not
                # void discovery for the others — log and move on.
                logger.exception(
                    "subscription_registry_package_import_failed package=%s",
                    package_path,
                )
                continue

            for _finder, name, _is_pkg in pkgutil.iter_modules(handlers_pkg.__path__):
                if name.startswith("_"):
                    continue
                module_path = f"{handlers_pkg.__name__}.{name}"
                try:
                    importlib.import_module(module_path)
                except Exception:
                    # One broken handler shouldn't void the whole boot — log loudly
                    # and continue. Surfaced via test_subscription_registry_discovery.
                    logger.exception(
                        "subscription_registry_handler_import_failed module=%s",
                        module_path,
                    )

    @classmethod
    def bind_all(cls, publisher, packages: tuple[str, ...] = ()) -> None:
        """Discover the handler ``packages`` then subscribe every entry to ``publisher``.

        Called once from the composition root (``infrastructure/persistence/ai/apps.py``
        ``ready()``). ``publisher`` is duck-typed — anything with
        ``subscribe(event_type, handler)`` works (production ``CeleryEventPublisher``;
        tests a stub). ``packages`` is the composition root's list of handler packages.
        """
        cls.discover(packages)
        for event_type, handler in cls._entries:
            publisher.subscribe(event_type, handler)
            logger.info(
                "subscription_registry_bound event=%s handler=%s",
                event_type.__name__,
                getattr(handler, "__qualname__", handler),
            )

    # ── Introspection / test helpers ─────────────────────────────────

    @classmethod
    def entries(cls) -> list[tuple[type[DomainEvent], EventHandler]]:
        """Read-only (shallow-copied) view of every registered subscription."""
        return list(cls._entries)

    @classmethod
    def clear(cls) -> None:
        """Drop every registered subscription. Test-only.

        Production code MUST NOT call this — it would silently break every
        detector → specialist path until the next process boot.
        """
        cls._entries.clear()
        cls._discovered = False


def subscribes_to(event_type: type[DomainEvent]):
    """Decorate an event-handler function with the domain event it consumes.

    Usage::

        @subscribes_to(FindingObserved)
        def handle_finding_observed(event) -> None:
            ...

    Stackable for handlers that react to multiple events. The function is returned
    unchanged — the decorator's only side effect is registering the subscription, so
    handlers stay callable as plain ``handler(event)`` for tests and ad-hoc use.
    """

    def decorator(handler: EventHandler) -> EventHandler:
        SubscriptionRegistry.register(event_type, handler)
        return handler

    return decorator
