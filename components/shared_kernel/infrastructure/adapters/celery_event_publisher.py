"""Celery-backed event publisher implementation.

Routes ``DomainEvent`` instances to registered subscriber callables
**asynchronously** via the Celery task queue.  Each subscriber call is
dispatched as a separate Celery task, giving you:

- fault isolation (one failing handler does not block others),
- independent retries per handler,
- horizontal scalability (handlers run across worker processes).

The publisher is transport-agnostic: whatever broker Celery is configured
to use (Redis today, SQS / Kafka tomorrow) is irrelevant to the event
system.  Swap the broker in Django settings and the event pipeline follows.

Registration still happens in the composition root (provider) at startup,
identical to ``LocalEventPublisher``.

For purely in-process / test scenarios, use ``LocalEventPublisher`` instead.
"""

from __future__ import annotations

import importlib
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID

from celery import shared_task

from components.shared_kernel.domain.events import DomainEvent
from components.shared_kernel.application.ports.event_publisher import EventPublisher

logger = logging.getLogger(__name__)

EventHandler = Callable[[DomainEvent], Any]

# ── Global handler registry ──────────────────────────────────────────
# Populated at import time by ``CeleryEventPublisher.subscribe()`` calls
# from the composition root.  The Celery task below reads from this
# registry when it executes inside a worker.

_handler_registry: dict[str, list[str]] = {}
_global_handlers: list[str] = []


def _handler_fqn(handler: EventHandler) -> str:
    """Fully-qualified ``module:qualname`` of *handler*."""
    module = handler.__module__
    qualname = handler.__qualname__
    return f"{module}:{qualname}"


def _resolve_handler(fqn: str) -> EventHandler:
    """Import and return the callable at *fqn* (``module:qualname``)."""
    module_path, qualname = fqn.rsplit(":", 1)
    module = importlib.import_module(module_path)
    obj: Any = module
    for attr in qualname.split("."):
        obj = getattr(obj, attr)
    return obj  # type: ignore[return-value]


# ── JSON helpers (UUID / datetime / date / time / Decimal aren't natively
# serialisable) ─────────────────────────────────────────────────────────
#
# Order of isinstance checks below matters: datetime is a subclass of date,
# so the datetime branch must come BEFORE the date branch — otherwise every
# datetime would be serialised as a bare YYYY-MM-DD without the time
# component.

class _EventEncoder(json.JSONEncoder):
    def default(self, o: object) -> Any:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, time):
            return o.isoformat()
        if isinstance(o, Decimal):
            # str() preserves precision; float() would silently round
            # money / accounting values that money domain code relies on.
            return str(o)
        return super().default(o)


def _serialise_event(event: DomainEvent) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(event), cls=_EventEncoder))


def _deserialise_event(event_type_fqn: str, data: dict[str, Any]) -> DomainEvent:
    """Reconstruct the concrete ``DomainEvent`` subclass from JSON data."""
    module_path, class_name = event_type_fqn.rsplit(".", 1)
    module = importlib.import_module(module_path)
    event_class: type[DomainEvent] = getattr(module, class_name)
    # Re-hydrate UUID / datetime / date / time / Decimal fields from
    # their string representations — symmetrical with _EventEncoder.
    # Order matters: datetime must be checked before date because their
    # string-repr type names overlap conceptually but parse differently.
    import dataclasses
    for f in dataclasses.fields(event_class):
        if f.name in data and data[f.name] is not None:
            # ``f.type`` is a string under ``from __future__ import
            # annotations`` and may be a union (e.g. ``"date | None"``,
            # ``"Optional[datetime]"``). Reduce it to the set of bare type
            # tokens so Optional fields rehydrate too — otherwise an
            # ``occurred_on: date | None`` round-trips through Celery JSON
            # and arrives as a raw ``str``, breaking ``.isoformat()`` in
            # handlers.
            type_names = _annotation_type_names(f.type)
            if type_names & {"UUID", "uuid.UUID"}:
                data[f.name] = UUID(data[f.name])
            elif type_names & {"datetime", "datetime.datetime"}:
                data[f.name] = datetime.fromisoformat(data[f.name])
            elif type_names & {"date", "datetime.date"}:
                data[f.name] = date.fromisoformat(data[f.name])
            elif type_names & {"time", "datetime.time"}:
                data[f.name] = time.fromisoformat(data[f.name])
            elif type_names & {"Decimal", "decimal.Decimal"}:
                data[f.name] = Decimal(data[f.name])
    return event_class(**data)


def _annotation_type_names(annotation: Any) -> set[str]:
    """Reduce a (possibly union/optional) field annotation to bare type tokens.

    Handles strings (PEP 563 deferred annotations) and real types, plus
    ``X | None``, ``Optional[X]`` and ``Union[X, None]`` wrappers. Returns
    e.g. ``{"date"}`` for ``"date | None"`` so Optional temporal/uuid/decimal
    fields are rehydrated the same as their non-optional counterparts.
    """
    text = (
        annotation
        if isinstance(annotation, str)
        else getattr(annotation, "__name__", str(annotation))
    )
    text = text.replace("Optional[", "").replace("Union[", "").replace("]", "")
    tokens: set[str] = set()
    for part in text.replace(",", "|").split("|"):
        token = part.strip()
        if token and token != "None":
            tokens.add(token)
    return tokens


# ── Celery task ──────────────────────────────────────────────────────

@shared_task(
    name="shared_kernel.handle_domain_event",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def _dispatch_to_handler(
    handler_fqn: str,
    event_type_fqn: str,
    event_data: dict[str, Any],
) -> None:
    """Celery task that resolves and invokes a single event handler.

    Each ``(handler, event)`` pair is dispatched as a separate task so
    failures in one handler do not affect others.
    """
    handler = _resolve_handler(handler_fqn)
    event = _deserialise_event(event_type_fqn, event_data)
    logger.info(
        "Handling %s with %s (event_id=%s)",
        event_type_fqn.rsplit(".", 1)[-1],
        handler_fqn,
        event.event_id,
    )
    handler(event)


# ── Publisher ────────────────────────────────────────────────────────

class CeleryEventPublisher(EventPublisher):
    """Asynchronous event publisher backed by Celery.

    Publishes each ``(handler, event)`` pair as a separate Celery task,
    providing fault isolation and independent retries.

    The underlying broker (Redis, RabbitMQ, SQS, Kafka) is transparent —
    swap it in Django/Celery settings and the event pipeline follows.
    """

    def subscribe(
        self,
        event_type: type[DomainEvent],
        handler: EventHandler,
    ) -> None:
        fqn = _handler_fqn(handler)
        event_key = f"{event_type.__module__}.{event_type.__qualname__}"
        _handler_registry.setdefault(event_key, []).append(fqn)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register *handler* to receive every published event."""
        _global_handlers.append(_handler_fqn(handler))

    def publish(self, event: DomainEvent) -> None:
        """Serialise *event* and dispatch to all matching subscribers via Celery."""
        event_type = type(event)
        event_key = f"{event_type.__module__}.{event_type.__qualname__}"
        event_data = _serialise_event(event)

        handler_fqns = [
            *_handler_registry.get(event_key, []),
            *_global_handlers,
        ]

        if not handler_fqns:
            logger.debug(
                "No subscribers for %s (event_id=%s)",
                event_type.__name__,
                event.event_id,
            )
            return

        for fqn in handler_fqns:
            _dispatch_to_handler.delay(fqn, event_key, event_data)

    # ── Introspection ────────────────────────────────────────────────

    @property
    def subscriber_count(self) -> int:
        typed = sum(len(hs) for hs in _handler_registry.values())
        return typed + len(_global_handlers)

    def clear(self) -> None:
        """Remove all subscriptions.  Useful for testing."""
        _handler_registry.clear()
        _global_handlers.clear()
