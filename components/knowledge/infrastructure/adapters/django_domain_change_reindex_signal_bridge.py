"""Generic post_save bridge for the Tier 2 #7 domain-change reindex flow.

Each instance of this class wires ONE Django ORM model's
``post_save`` to ONE handler.  Four registrations land in
``WorkspaceIndexSignalProvider.register_signal_handlers`` — one each
for ``Recipient`` / ``Donation`` / ``Grant`` / ``Campaign`` — so the
workspace snapshot stays fresh between ``Workspace.save()`` events
and the nightly beat.

Bridges live in the knowledge context (this file), but listen to
sender models from other bounded contexts.  The cross-context read
is acceptable here because:

* The bridge listens via Django's signal framework — it does NOT
  import behavior, only the model class as a signal sender.
* The handler (use case in the application layer) treats the
  instance as a plain object: reads ``workspace_id`` defensively,
  never calls domain methods.

Errors in the handler are logged but never propagated — a signal
handler that raises would otherwise abort the caller's save
transaction, which is unacceptable when the caller is a donation
checkout.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #7.
"""
from __future__ import annotations

import logging
from typing import Type

from django.db.models import Model
from django.db.models.signals import post_save

logger = logging.getLogger(__name__)


class DjangoDomainChangeReindexSignalBridge:
    """Registers a single ``post_save`` handler for one sender model."""

    def __init__(
        self,
        *,
        sender: Type[Model],
        dispatch_uid: str,
        domain_label: str,
    ) -> None:
        self._sender = sender
        self._dispatch_uid = dispatch_uid
        self._domain_label = domain_label

    def register(self, *, handler) -> None:
        """Wire ``post_save`` for ``sender`` to ``handler.execute``.

        ``dispatch_uid`` keeps the connect idempotent — multiple
        process boots register the same uid and Django de-dupes.
        ``weak=False`` so the receiver isn't garbage-collected once
        ``register`` returns and the bridge object falls out of scope.
        """

        post_save.connect(
            self._build_receiver(handler=handler),
            sender=self._sender,
            weak=False,
            dispatch_uid=self._dispatch_uid,
        )
        logger.debug(
            "knowledge: registered domain-change reindex bridge "
            "sender=%s dispatch_uid=%s",
            self._sender.__name__,
            self._dispatch_uid,
        )

    def _build_receiver(self, *, handler):
        domain_label = self._domain_label

        def receiver(sender, instance, created, **kwargs):  # noqa: ARG001
            try:
                handler.execute(instance=instance, created=created)
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "knowledge: domain-change reindex bridge handler "
                    "failed domain=%s sender=%s",
                    domain_label,
                    sender.__name__,
                )

        return receiver
