"""Composition root for the response context — wires ports to adapters.

Policy decision (which adapter implements which port) owned by the application
layer per Explicit Architecture. Own-context infrastructure imports are allowed
here (the provider is the one sanctioned slot for them).
"""

from __future__ import annotations

from components.response.application.ports.cloud_response_port import CloudResponsePort
from components.response.application.ports.response_action_store_port import (
    ResponseActionStorePort,
)
from components.response.application.service import ResponseActionService
from components.response.application.use_cases.approve_response_action_use_case import (
    ApproveResponseActionUseCase,
)
from components.response.application.use_cases.propose_response_action_use_case import (
    ProposeResponseActionUseCase,
)
from components.response.application.use_cases.reject_response_action_use_case import (
    RejectResponseActionUseCase,
)
from components.response.application.use_cases.rollback_response_action_use_case import (
    RollbackResponseActionUseCase,
)


def build_cloud_response_port() -> CloudResponsePort:
    from components.response.infrastructure.adapters.boto3_cloud_response_adapter import (
        Boto3CloudResponseAdapter,
    )

    return Boto3CloudResponseAdapter()


def build_response_store() -> ResponseActionStorePort:
    from components.response.infrastructure.repositories.response_action_repository import (
        DjangoResponseActionRepository,
    )

    return DjangoResponseActionRepository()


def build_response_service(
    *,
    store: ResponseActionStorePort | None = None,
    cloud_port: CloudResponsePort | None = None,
) -> ResponseActionService:
    """Assemble the response service. ``store`` / ``cloud_port`` are injectable
    so tests wire fakes; production omits them and gets the real adapters."""
    store = store or build_response_store()
    cloud_port = cloud_port or build_cloud_response_port()
    return ResponseActionService(
        propose=ProposeResponseActionUseCase(store=store, cloud_port=cloud_port),
        approve=ApproveResponseActionUseCase(store=store, cloud_port=cloud_port),
        reject=RejectResponseActionUseCase(store=store),
        rollback=RollbackResponseActionUseCase(store=store, cloud_port=cloud_port),
        store=store,
    )
