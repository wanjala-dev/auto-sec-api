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
from components.remediation.application.use_cases.propagate_remediation_outcomes_use_case import (
    PropagateRemediationOutcomesUseCase,
)
from components.remediation.application.use_cases.record_remediation_entry_use_case import (
    RecordRemediationEntryUseCase,
)
from components.remediation.application.use_cases.revoke_remediation_entry_use_case import (
    RevokeRemediationEntryUseCase,
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


def build_remediation_governance() -> RemediationGovernancePort:
    from components.remediation.infrastructure.adapters.remediation_governance_adapter import (
        RemediationGovernanceAdapter,
    )

    return RemediationGovernanceAdapter()


def build_remediation_audit() -> RemediationAuditPort:
    from components.remediation.infrastructure.adapters.remediation_audit_adapter import (
        RemediationAuditAdapter,
    )

    return RemediationAuditAdapter()


def _reembed_dispatch(entry_id, workspace_id) -> None:
    """Re-embed a prior whose score changed (P5). Reuses the capture handler's
    after-commit embed dispatch — no celery import in this application module."""
    from components.remediation.application.handlers.remediation_capture_handler import (
        dispatch_embed,
    )

    dispatch_embed(entry_id, workspace_id)


def _build_on_admit(store: RemediationEntryStorePort):
    """The post-admission hook wired into the gate: propagate outcome signals to
    the priors of a newly-admitted fix (P5). Fires ONCE per new admission."""
    propagate = PropagateRemediationOutcomesUseCase(store=store, reembed=_reembed_dispatch)
    return propagate.execute


def build_remediation_retrieval() -> RemediationRetrievalPort:
    """The read side of Remediation Memory (ADR 0012 P4) — the triage advisor
    resolves this to ground a suggestion in the workspace's vetted prior fixes."""
    from components.remediation.infrastructure.adapters.pgvector_remediation_retrieval_adapter import (
        PgVectorRemediationRetrievalAdapter,
    )

    return PgVectorRemediationRetrievalAdapter()


def build_embed_remediation_entry_use_case() -> EmbedRemediationEntryUseCase:
    """Wire the embed-on-capture use case to the knowledge-owned write door.

    The knowledge ``CorpusChunkIndexPort`` is resolved through knowledge's OWN
    application provider (cross-context via the application surface, never a
    knowledge-infrastructure import) — knowledge stays the sole writer of its store.
    """
    from components.knowledge.application.providers.corpus_chunk_index_provider import (
        build_corpus_chunk_index_port,
    )
    from components.remediation.application.use_cases.embed_remediation_entry_use_case import (
        EmbedRemediationEntryUseCase,
    )

    return EmbedRemediationEntryUseCase(index=build_corpus_chunk_index_port())


def build_revoke_remediation_entry_use_case(
    *,
    store: RemediationEntryStorePort | None = None,
    sign_off_gate: SignOffGatePort | None = None,
    governance: RemediationGovernancePort | None = None,
    audit: RemediationAuditPort | None = None,
) -> RevokeRemediationEntryUseCase:
    """Wire the governance-gated revocation use case (P5).

    The knowledge ``CorpusChunkIndexPort`` (the embedding-delete door) is resolved
    through knowledge's OWN provider — cross-context via the application surface,
    never a knowledge-infrastructure import."""
    from components.knowledge.application.providers.corpus_chunk_index_provider import (
        build_corpus_chunk_index_port,
    )

    return RevokeRemediationEntryUseCase(
        store=store or build_remediation_store(),
        corpus_index=build_corpus_chunk_index_port(),
        governance=governance or build_remediation_governance(),
        sign_off_gate=sign_off_gate or build_sign_off_gate(),
        audit=audit or build_remediation_audit(),
    )


def build_remediation_service(
    *,
    store: RemediationEntryStorePort | None = None,
    sign_off_gate: SignOffGatePort | None = None,
    finding_facts: FindingRemediationFactsPort | None = None,
    governance: RemediationGovernancePort | None = None,
    audit: RemediationAuditPort | None = None,
    propagate_outcomes: bool = True,
) -> RemediationService:
    """Assemble the remediation service. Ports are injectable so tests wire
    fakes; production omits them and gets the real adapters.

    ``propagate_outcomes`` wires the P5 outcome-propagation hook into the gate
    (fires on each NEW admission). Tests that want to isolate the gate can pass
    ``False``."""
    store = store or build_remediation_store()
    sign_off_gate = sign_off_gate or build_sign_off_gate()
    finding_facts = finding_facts or build_finding_facts()
    on_admit = _build_on_admit(store) if propagate_outcomes else None
    return RemediationService(
        record=RecordRemediationEntryUseCase(
            store=store,
            sign_off_gate=sign_off_gate,
            finding_facts=finding_facts,
            on_admit=on_admit,
        ),
        store=store,
        revoke=build_revoke_remediation_entry_use_case(
            store=store,
            sign_off_gate=sign_off_gate,
            governance=governance,
            audit=audit,
        ),
    )
