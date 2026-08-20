"""Queue-level audit sink for sign-off decisions.

Implements the kernel's :class:`SignOffAuditPort` by writing every queue
decision (approved / changes-requested / rejected) to the shared, append-only
``EntityAuditLog`` — the same table the recycle bin, field-edit history, and the
reports sign-off audit already use (reused, not forked — the "one ledger" rule).

Rows are recorded against the ARTIFACT's own content type (e.g.
``content.newsletter``), supplied by the registered adapter via
``audit_content_type()``, with ``field_name = "review_state"``. The field name
is what keeps this a complementary queue-decision trail rather than a
duplicate of a context's own field history — and it has the added benefit that
a sign-off decision now shows up on the artifact's audit trail, where someone
investigating that artifact will actually look.

WHY THIS CHANGED — it was writing to nowhere
--------------------------------------------
Rows were previously recorded under a SYNTHETIC ``"signoff.<artifact_type>"``.
``EntityAuditLog`` is ContentType-backed, and the repository resolves that
string as ``app_label.model``. There is no Django app ``signoff`` and no model
``newsletter`` inside one, so ContentType resolution returned None, the
repository returned None, and the write was dropped. Not an exception — the
adapter's ``except Exception`` never even fired. Every sign-off decision this
product ever recorded went nowhere, silently, while the API returned 200.

It was invisible because the only tests of the trail asserted against an
in-memory fake audit sink, which faithfully recorded calls the production
adapter then discarded. See
``components/sign_off/tests/integration/test_kernel_audit_adapter_writes.py``,
which drives the real adapter against a real database.

The artifact's workspace is resolved through the sign-off registry adapter
(``adapter.workspace_id``) — the kernel never touches a foreign context's ORM
directly. An audit write must NEVER fail the user-facing decision, so failures
are logged loudly and swallowed (same contract the recycle-bin + reports audit
adapters use).
"""

from __future__ import annotations

import logging

from components.sign_off.application.ports.sign_off_audit_port import SignOffAuditPort
from components.sign_off.application.providers.sign_off_registry_provider import (
    get_sign_off_registry,
)

logger = logging.getLogger(__name__)

_FIELD_NAME = "review_state"


class KernelSignOffAuditAdapter(SignOffAuditPort):
    def __init__(self, audit_repository=None) -> None:
        self._repo = audit_repository

    def record(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        event: str,
        actor_id: str | None,
        detail: dict | None = None,
    ) -> None:
        detail = detail or {}
        try:
            entity_type = self._entity_type(artifact_type)
            if not entity_type:
                # Loud, not silent. An unauditable approval gate is a product
                # defect, and the previous behaviour — dropping the row with
                # no signal at all — is precisely what hid this for so long.
                logger.error(
                    "sign_off.queue_audit_unauditable artifact_type=%s artifact_id=%s event=%s "
                    "reason=adapter_declared_no_audit_content_type",
                    artifact_type,
                    artifact_id,
                    event,
                )
                return

            reason = detail.get("override_reason") or detail.get("note") or ""
            entry = self._repository().record(
                workspace_id=self._workspace_id(artifact_type, artifact_id),
                entity_type=entity_type,
                entity_id=str(artifact_id),
                field_name=_FIELD_NAME,
                previous_value=None,
                new_value=event,
                actor_id=str(actor_id) if actor_id is not None else None,
                reason=reason,
            )
            if entry is None:
                # The repository returns None when the content type cannot be
                # resolved. That is the exact failure mode that made this a
                # no-op; it must never be quiet again.
                logger.error(
                    "sign_off.queue_audit_write_dropped artifact_type=%s artifact_id=%s event=%s "
                    "entity_type=%s reason=content_type_unresolvable",
                    artifact_type,
                    artifact_id,
                    event,
                    entity_type,
                )
        except Exception:
            # Audit failure must never break the sign-off decision itself.
            logger.exception(
                "sign_off.queue_audit_write_failed artifact_type=%s artifact_id=%s event=%s",
                artifact_type,
                artifact_id,
                event,
            )

    def _repository(self):
        if self._repo is None:
            from components.audit.application.providers.entity_audit_log_repository_provider import (
                get_entity_audit_log_repository_provider,
            )

            self._repo = get_entity_audit_log_repository_provider().repository()
        return self._repo

    @staticmethod
    def _workspace_id(artifact_type: str, artifact_id: str) -> str | None:
        adapter = get_sign_off_registry().get_adapter(artifact_type)
        return adapter.workspace_id(str(artifact_id))

    @staticmethod
    def _entity_type(artifact_type: str) -> str | None:
        adapter = get_sign_off_registry().get_adapter(artifact_type)
        return adapter.audit_content_type()
