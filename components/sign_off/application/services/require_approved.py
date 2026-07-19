"""The kernel's teeth — the guard every send/apply action calls first.

Usage at any outbound/apply choke point (report dispatch, workflow email node,
budget-estimate apply, newsletter send):

    from components.sign_off.application.services.require_approved import require_approved
    require_approved("financial_report", str(report.id))   # raises NotApprovedError unless approved
    ... proceed to send ...

Keeping this a tiny standalone function (rather than a method on a heavy
service) means a send path doesn't need to construct the whole sign-off service
just to check the gate.
"""

from __future__ import annotations

from components.sign_off.application.providers.sign_off_registry_provider import (
    SignOffRegistry,
    get_sign_off_registry,
)
from components.sign_off.domain.errors import NotApprovedError
from components.sign_off.domain.value_objects.review_state import ReviewState


def require_approved(
    artifact_type: str,
    artifact_id: str,
    *,
    registry: SignOffRegistry | None = None,
) -> None:
    """Raise ``NotApprovedError`` unless the artifact is signed off.

    ``registry`` is injectable for tests; production callers omit it and get the
    process-wide registry.
    """
    registry = registry or get_sign_off_registry()
    adapter = registry.get_adapter(artifact_type)
    state = adapter.get_state(artifact_id)
    if state != ReviewState.APPROVED:
        raise NotApprovedError(artifact_type, artifact_id, state)
