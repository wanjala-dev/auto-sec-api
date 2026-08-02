"""Composition root for the remediation context — wires ports to adapters.

Policy decision (which adapter implements which port) owned by the application
layer per Explicit Architecture. Own-context infrastructure imports are allowed
here (the provider is the one sanctioned slot for them). The gated use case is
assembled here with its three read-ports so nothing else can construct it with a
weakened gate.
"""

from __future__ import annotations

from components.remediation.application.ports.finding_remediation_facts_port import (
    FindingRemediationFactsPort,
)
from components.remediation.application.ports.remediation_entry_store_port import (
    RemediationEntryStorePort,
)
from components.remediation.application.ports.sign_off_gate_port import SignOffGatePort
from components.remediation.application.service import RemediationService
from components.remediation.application.use_cases.record_remediation_entry_use_case import (
    RecordRemediationEntryUseCase,
)


def build_remediation_store() -> RemediationEntryStorePort:
    from components.remediation.infrastructure.repositories.remediation_entry_repository import (
        DjangoRemediationEntryRepository,
    )

    return DjangoRemediationEntryRepository()


def build_sign_off_gate() -> SignOffGatePort:
    from components.remediation.infrastructure.adapters.sign_off_gate_adapter import (
        SignOffGateAdapter,
    )

    return SignOffGateAdapter()


def build_finding_facts() -> FindingRemediationFactsPort:
    from components.remediation.infrastructure.adapters.board_finding_facts_repository import (
        BoardFindingFactsRepository,
    )

    return BoardFindingFactsRepository()


def build_remediation_service(
    *,
    store: RemediationEntryStorePort | None = None,
    sign_off_gate: SignOffGatePort | None = None,
    finding_facts: FindingRemediationFactsPort | None = None,
) -> RemediationService:
    """Assemble the remediation service. Ports are injectable so tests wire
    fakes; production omits them and gets the real adapters."""
    store = store or build_remediation_store()
    sign_off_gate = sign_off_gate or build_sign_off_gate()
    finding_facts = finding_facts or build_finding_facts()
    return RemediationService(
        record=RecordRemediationEntryUseCase(
            store=store,
            sign_off_gate=sign_off_gate,
            finding_facts=finding_facts,
        ),
        store=store,
    )
