"""Composition root for the AI bounded context.

Each ``build_*`` factory wires ports → adapters → use cases so that
controllers only depend on this single provider class.

Dynamic provider registries (``AILlmProvider``, ``AIEmbeddingsProvider``,
``AIVectorStoreProvider``) resolve the right infrastructure adapter at
runtime based on a provider slug, following the pattern::

    llm = AIProvider.llm().get_port("openai", model_name="gpt-4")
    emb = AIProvider.embeddings().get_port("openai")
    vs  = AIProvider.vector_store().get_port()           # uses VECTOR_STORE_PROVIDER env var
    vs  = AIProvider.vector_store().get_port("pinecone")  # explicit override
"""

from __future__ import annotations

from components.agents.application.ports.artifact_store_port import ArtifactStorePort
from components.agents.application.ports.tool_registry_port import ToolRegistryPort
from components.agents.application.queries.agent_engagement_query import (
    FetchAgentCommentsQuery,
    FetchAgentRatingsQuery,
    FetchSharedAgentQuery,
)
from components.agents.application.queries.agent_execution_query import (
    FetchAgentExecutionDetailQuery,
    FetchAgentExecutionListQuery,
    FetchAgentMemoryQuery,
)
from components.agents.application.queries.agent_graph_query import FetchAgentGraphQuery
from components.agents.application.queries.deep_run_observability_query import (
    FetchDeepRunEventsQuery,
    FetchDeepRunSnapshotQuery,
    FetchDeepRunStatsQuery,
)
from components.agents.application.queries.workspace_search_query import WorkspaceSearchQuery
from components.agents.application.use_cases.agent_chat_use_case import AgentChatUseCase
from components.agents.application.use_cases.agent_engagement_use_case import (
    CommentAgentUseCase,
    FollowAgentUseCase,
    LikeAgentUseCase,
    RateAgentUseCase,
    RevokeShareUseCase,
    ShareAgentUseCase,
    UnfollowAgentUseCase,
    UnlikeAgentUseCase,
)
from components.agents.application.use_cases.agent_entitlement_use_case import (
    ListAgentsQuery,
    ListAgentTypesQuery,
    SetAgentEntitlementUseCase,
)
from components.agents.application.use_cases.agent_execution_command_use_case import (
    ExecuteAgentUseCase,
)
from components.agents.application.use_cases.agent_lifecycle_use_case import (
    AgentStateUseCase,
    CreateAgentUseCase,
    DeleteAgentUseCase,
)
from components.agents.application.use_cases.agent_memory_command_use_case import (
    AddAgentSystemMessageUseCase,
    ClearAgentMemoryUseCase,
)
from components.agents.application.use_cases.agent_profile_use_case import (
    GetAgentProfileQuery,
    GetAgentStateQuery,
    PatchAgentProfileUseCase,
    PatchAgentSettingsUseCase,
)
from components.agents.application.use_cases.deep_run_use_case import (
    DeepPlanAndRunUseCase,
    DeepRunPlanUseCase,
)
from components.agents.application.use_cases.pdf_chat_use_case import PdfChatUseCase
from components.agents.application.use_cases.pdf_summary_use_case import PdfSummaryUseCase
from components.agents.application.use_cases.teammate_profile_use_case import (
    GetTeammateProfileUseCase,
    UpdateTeammateProfileUseCase,
)
from components.agents.infrastructure.adapters.agent_service_adapter import AgentServiceAdapter
from components.agents.infrastructure.adapters.artifact_store_adapter import OrmArtifactStoreAdapter
from components.agents.infrastructure.adapters.deep_run_adapter import DeepRunAdapter
from components.agents.infrastructure.adapters.entitlement_adapter import EntitlementAdapter
from components.agents.infrastructure.adapters.tool_registry_adapter import DetectorRegistryAdapter
from components.knowledge.application.providers.ai_embeddings_provider import AIEmbeddingsProvider
from components.knowledge.application.providers.ai_llm_provider import AILlmProvider
from components.knowledge.application.providers.ai_reranker_provider import AIRerankerProvider
from components.knowledge.application.providers.ai_vector_store_provider import AIVectorStoreProvider


class AIProvider:
    # ── Command / Query Bus ─────────────────────────────────────────

    @staticmethod
    def build_command_bus():
        """Wire all command handlers into an in-memory command bus.

        This is the composition root for CQRS dispatching.
        Controllers dispatch ``Command`` objects through the bus instead
        of calling use cases directly.
        """
        from components.agents.application.commands.agent_chat_command import AgentChatCommand
        from components.agents.application.commands.agent_lifecycle_command import (
            AgentStateCommand,
            CreateAgentCommand,
            DeleteAgentCommand,
        )
        from components.agents.application.commands.deep_run_command import DeepPlanAndRunCommand, DeepRunPlanCommand
        from components.agents.application.commands.pdf_chat_command import PdfChatCommand
        from components.agents.application.commands.pdf_summary_command import PdfSummaryCommand
        from components.shared_kernel.infrastructure.adapters.in_memory_command_bus import (
            InMemoryCommandBus,
        )

        bus = InMemoryCommandBus()

        # ── Middleware ──
        from components.shared_kernel.infrastructure.middleware.logging_middleware import (
            logging_middleware,
        )
        from components.shared_kernel.infrastructure.middleware.transaction_middleware import (
            transaction_middleware,
        )

        bus.add_middleware(logging_middleware)
        bus.add_middleware(transaction_middleware)

        # ── Agent lifecycle ──
        bus.register(CreateAgentCommand, AIProvider.build_create_agent_use_case())
        bus.register(AgentStateCommand, AIProvider.build_agent_state_use_case())
        bus.register(DeleteAgentCommand, AIProvider.build_delete_agent_use_case())

        # ── Chat / AI ──
        bus.register(AgentChatCommand, AIProvider.build_agent_chat_use_case())
        bus.register(PdfChatCommand, AIProvider.build_pdf_chat_use_case())
        bus.register(PdfSummaryCommand, AIProvider.build_pdf_summary_use_case())

        # ── Deep runs ──
        bus.register(DeepRunPlanCommand, AIProvider.build_deep_run_plan_use_case())
        bus.register(DeepPlanAndRunCommand, AIProvider.build_deep_plan_and_run_use_case())

        return bus

    @staticmethod
    def build_event_publisher():
        """Build the in-process event publisher singleton.

        Subscribe domain event handlers here as needed::

            publisher = AIProvider.build_event_publisher()
            publisher.subscribe(AgentCreatedEvent, some_handler)
        """
        from components.shared_kernel.infrastructure.adapters.local_event_publisher import (
            LocalEventPublisher,
        )

        return LocalEventPublisher()

    @staticmethod
    def build_tool_access_resolver(*, enable_caching: bool = True, cache_ttl: int = 300):
        """Wire all tool access strategy adapters into the resolver.

        When ``enable_caching`` is True (default), ORM, MCP, and WEB
        adapters are wrapped with a ``CachingToolAccessAdapter`` decorator
        that transparently caches deterministic results.  FILE adapters
        are not cached (filesystem reads should always be fresh).

        Usage::

            resolver = AIProvider.build_tool_access_resolver()
            adapter = resolver.resolve(tool_entity)
            result = adapter.execute(
                operation="list",
                workspace_id="...",
                params={},
                access_config=tool_entity.access_config,
            )
        """
        from components.agents.application.services.tool_access_resolver import (
            ToolAccessResolver,
        )
        from components.agents.domain.enums import ToolAccessStrategy
        from components.agents.infrastructure.adapters.tool_access.caching_adapter import (
            CachingToolAccessAdapter,
        )
        from components.agents.infrastructure.adapters.tool_access.file_adapter import (
            FileToolAccessAdapter,
        )
        from components.agents.infrastructure.adapters.tool_access.mcp_adapter import (
            McpToolAccessAdapter,
        )
        from components.agents.infrastructure.adapters.tool_access.orm_adapter import (
            OrmToolAccessAdapter,
        )
        from components.agents.infrastructure.adapters.tool_access.web_adapter import (
            WebToolAccessAdapter,
        )

        orm_adapter = OrmToolAccessAdapter()
        mcp_adapter = McpToolAccessAdapter()
        web_adapter = WebToolAccessAdapter()
        file_adapter = FileToolAccessAdapter()

        if enable_caching:
            orm_adapter = CachingToolAccessAdapter(inner=orm_adapter, ttl=cache_ttl)
            mcp_adapter = CachingToolAccessAdapter(inner=mcp_adapter, ttl=cache_ttl)
            web_adapter = CachingToolAccessAdapter(inner=web_adapter, ttl=cache_ttl)
            # FILE adapter intentionally not cached — reads should be fresh

        resolver = ToolAccessResolver()
        resolver.register(ToolAccessStrategy.ORM, orm_adapter)
        resolver.register(ToolAccessStrategy.MCP, mcp_adapter)
        resolver.register(ToolAccessStrategy.WEB, web_adapter)
        resolver.register(ToolAccessStrategy.FILE, file_adapter)
        return resolver

    @staticmethod
    def build_model_selection_policy():
        """Return the model selection policy (pure domain — no deps)."""
        from components.agents.domain.policies.model_selection_policy import (
            ModelSelectionPolicy,
        )

        return ModelSelectionPolicy()

    @staticmethod
    def build_tool_execution_policy():
        """Return the tool execution policy (pure domain — no deps)."""
        from components.agents.domain.policies.tool_execution_policy import (
            ToolExecutionPolicy,
        )

        return ToolExecutionPolicy()

    # ── Dynamic provider registries (slug → port) ────────────────────

    @staticmethod
    def llm() -> AILlmProvider:
        """Return the LLM provider registry.

        Usage::

            llm_port = AIProvider.llm().get_port("openai")
            llm_port = AIProvider.llm().get_default_port(model_name="gpt-4")
        """
        return AILlmProvider()

    @staticmethod
    def embeddings() -> AIEmbeddingsProvider:
        """Return the embeddings provider registry.

        Usage::

            emb_port = AIProvider.embeddings().get_port("openai")
        """
        return AIEmbeddingsProvider()

    @staticmethod
    def vector_store() -> AIVectorStoreProvider:
        """Return the vector-store provider registry.

        Usage::

            vs_port = AIProvider.vector_store().get_port()             # env-var default
            vs_port = AIProvider.vector_store().get_port("pinecone")   # explicit
            vs_port = AIProvider.vector_store().get_port("chroma")
            vs_port = AIProvider.vector_store().get_port("faiss")
            vs_port = AIProvider.vector_store().get_port("s3")
        """
        return AIVectorStoreProvider()

    @staticmethod
    def build_faithfulness_verifier():
        """Return the deterministic groundedness checker.

        Exposed through the application layer so other contexts (content's
        send-time faithfulness gate) reach it via the agents public surface
        rather than importing the agents domain directly.
        """
        from components.agents.domain.services.faithfulness_verifier import (
            FaithfulnessVerifier,
        )

        return FaithfulnessVerifier()

    # ── Use cases ────────────────────────────────────────────────────

    @staticmethod
    def build_ai_quality_overview_query():
        from components.agents.application.queries.ai_quality_overview_query import (
            FetchAIQualityOverviewQuery,
        )
        from components.agents.infrastructure.repositories.ai_analytics_repository import (
            OrmAIAnalyticsRepository,
        )

        return FetchAIQualityOverviewQuery(port=OrmAIAnalyticsRepository())

    @staticmethod
    def build_create_agent_use_case() -> CreateAgentUseCase:
        return CreateAgentUseCase(agent_service=AgentServiceAdapter())

    @staticmethod
    def build_agent_state_use_case() -> AgentStateUseCase:
        return AgentStateUseCase(agent_service=AgentServiceAdapter())

    @staticmethod
    def build_delete_agent_use_case() -> DeleteAgentUseCase:
        return DeleteAgentUseCase(agent_service=AgentServiceAdapter())

    @staticmethod
    def build_execute_agent_use_case() -> ExecuteAgentUseCase:
        from components.agents.infrastructure.repositories.agent_execution_command_repository import (
            OrmAgentExecutionCommandRepository,
        )

        return ExecuteAgentUseCase(port=OrmAgentExecutionCommandRepository())

    @staticmethod
    def build_ai_run_quota():
        """Monthly metered-AI quota port (execute + deep_run, not chat)."""
        from components.agents.infrastructure.adapters.ai_run_quota_adapter import (
            AiRunQuotaAdapter,
        )

        return AiRunQuotaAdapter()

    # ── Entitlement / Listing ─────────────────────────────────────────

    @staticmethod
    def _entitlement_port():
        from components.agents.infrastructure.repositories.agent_entitlement_repository import (
            OrmAgentEntitlementRepository,
        )

        return OrmAgentEntitlementRepository()

    @staticmethod
    def build_set_entitlement_use_case() -> SetAgentEntitlementUseCase:
        return SetAgentEntitlementUseCase(port=AIProvider._entitlement_port())

    @staticmethod
    def build_list_agents_query() -> ListAgentsQuery:
        return ListAgentsQuery(port=AIProvider._entitlement_port())

    @staticmethod
    def build_list_agent_types_query() -> ListAgentTypesQuery:
        return ListAgentTypesQuery(port=AIProvider._entitlement_port())

    @staticmethod
    def build_session_memory_port():
        from components.agents.infrastructure.adapters.session_memory_adapter import (
            OrmSessionMemoryAdapter,
        )

        return OrmSessionMemoryAdapter()

    @staticmethod
    def build_workspace_ai_config_port():
        from components.agents.infrastructure.adapters.workspace_ai_config_adapter import (
            OrmWorkspaceAIConfigAdapter,
        )

        return OrmWorkspaceAIConfigAdapter()

    @staticmethod
    def _deep_run_query_port():
        from components.agents.infrastructure.repositories.orm_deep_run_query_repository import (
            OrmDeepRunQueryRepository,
        )

        return OrmDeepRunQueryRepository()

    @staticmethod
    def build_deep_run_snapshot_query() -> FetchDeepRunSnapshotQuery:
        return FetchDeepRunSnapshotQuery(port=AIProvider._deep_run_query_port())

    @staticmethod
    def build_deep_run_events_query() -> FetchDeepRunEventsQuery:
        return FetchDeepRunEventsQuery(port=AIProvider._deep_run_query_port())

    @staticmethod
    def build_deep_run_stats_query() -> FetchDeepRunStatsQuery:
        return FetchDeepRunStatsQuery(port=AIProvider._deep_run_query_port())

    @staticmethod
    def build_agent_chat_use_case() -> AgentChatUseCase:
        from components.agents.infrastructure.adapters.workspace_brand_voice_adapter import (
            WorkspaceBrandVoiceAdapter,
        )

        return AgentChatUseCase(
            deep_plan_and_run=AIProvider.build_deep_plan_and_run_use_case(),
            entitlement=EntitlementAdapter(),
            ai_config_port=AIProvider.build_workspace_ai_config_port(),
            session_memory=AIProvider.build_session_memory_port(),
            # Canonical voice lives on the brand kit (WorkspaceTheme), not
            # WorkspaceAIConfig — one voice, every AI surface.
            brand_voice_port=WorkspaceBrandVoiceAdapter(),
        )

    @staticmethod
    def reranker() -> AIRerankerProvider:
        """Return the reranker provider registry.

        Usage::

            reranker_port = AIProvider.reranker().get_port("cross-encoder")
        """
        return AIRerankerProvider()

    @staticmethod
    def build_pdf_chat_use_case() -> PdfChatUseCase:
        """Wire LLM + vector-store + reranker ports into the PDF chat use case."""
        reranker = None
        try:
            reranker = AIRerankerProvider().get_port()
        except Exception:
            pass  # Reranker is optional — graceful degradation
        return PdfChatUseCase(
            llm=AILlmProvider().get_port(
                "openai",
                model_name="gpt-3.5-turbo",
                temperature=0.3,
            ),
            vector_store=AIVectorStoreProvider().get_port(),
            reranker=reranker,
        )

    @staticmethod
    def build_pdf_summary_use_case() -> PdfSummaryUseCase:
        """Wire LLM + vector-store ports into the PDF summary use case."""
        return PdfSummaryUseCase(
            llm=AILlmProvider().get_port(
                "openai",
                model_name="gpt-3.5-turbo",
                temperature=0.3,
            ),
            vector_store=AIVectorStoreProvider().get_port(),
        )

    @staticmethod
    def build_deep_run_plan_use_case() -> DeepRunPlanUseCase:
        return DeepRunPlanUseCase(deep_run=DeepRunAdapter())

    @staticmethod
    def build_deep_plan_and_run_use_case() -> DeepPlanAndRunUseCase:
        return DeepPlanAndRunUseCase(deep_run=DeepRunAdapter())

    @staticmethod
    def build_generate_interactive_draft_use_case():
        """Wire the workspace-retrieval port + LLM port into the grounded,
        non-persisting interactive-draft use case (SEE-169).

        Used by the content editor's "Ask AI" path
        (``LangchainWritingAiAdapter.draft_for_kind``). Grounds against
        the same ``WorkspaceRetrievalPort`` the deep-run planner prefetch
        uses; generates via the knowledge ``LlmPort``. Persists nothing.

        SEE-170: also wires the ``EntityFactSheetPort`` adapter so
        entity-update kinds ground in the linked record's real data.
        SEE-171: the use case runs a deterministic faithfulness check on the
        output (no wiring needed — pure domain service).
        SEE-172: wires the ``VoiceProfilePort`` adapter so the draft is
        steered by the workspace's brand voice (style only — never grounding).
        """
        from components.agents.application.use_cases.generate_interactive_draft_use_case import (
            GenerateInteractiveDraftUseCase,
        )
        from components.agents.infrastructure.adapters.workspace_brand_voice_adapter import (
            WorkspaceBrandVoiceAdapter,
        )
        from components.agents.infrastructure.adapters.workspace_voice_card_adapter import (
            WorkspaceVoiceCardAdapter,
        )
        from components.knowledge.application.providers.document_retrieval_provider import (
            document_retrieval,
        )
        from components.knowledge.application.providers.workspace_retrieval_provider import (
            workspace_retrieval,
        )

        return GenerateInteractiveDraftUseCase(
            retrieval_port=workspace_retrieval(),
            llm_port=AILlmProvider().get_default_port(
                model_name="gpt-3.5-turbo",
                temperature=0.4,
            ),
            # Per-entity fact-sheet grounding grounded against nonprofit
            # domain entities (recipients/donations/events) that no longer
            # exist in this fork; disabled — drafting still grounds via
            # workspace + document retrieval.
            fact_sheet_port=None,
            # Task #16: author-SELECTED uploaded documents are retrieved
            # directly (the uploaded-documents store) and lead the grounding
            # set — selection beats hoping workspace-wide ranking surfaces
            # the file.
            document_retrieval_port=document_retrieval(),
            # SEE-172: one voice source, not a parallel model — the brand
            # kit's canonical tone/guidelines plus the AI profile's language
            # rules, rendered to a style card kept out of the grounding set.
            voice_profile_port=WorkspaceVoiceCardAdapter(
                config_port=AIProvider.build_workspace_ai_config_port(),
                brand_voice_port=WorkspaceBrandVoiceAdapter(),
            ),
        )

    # ── Agent profile / state ────────────────────────────────────────

    @staticmethod
    def _profile_port():
        from components.agents.infrastructure.repositories.agent_profile_repository import (
            OrmAgentProfileRepository,
        )

        return OrmAgentProfileRepository()

    @staticmethod
    def build_get_agent_state_query() -> GetAgentStateQuery:
        return GetAgentStateQuery(port=AIProvider._profile_port())

    @staticmethod
    def build_get_agent_profile_query() -> GetAgentProfileQuery:
        return GetAgentProfileQuery(port=AIProvider._profile_port())

    @staticmethod
    def build_patch_agent_profile_use_case() -> PatchAgentProfileUseCase:
        return PatchAgentProfileUseCase(port=AIProvider._profile_port())

    @staticmethod
    def build_patch_agent_settings_use_case() -> PatchAgentSettingsUseCase:
        return PatchAgentSettingsUseCase(port=AIProvider._profile_port())

    # ── Engagement use cases ──────────────────────────────────────────

    @staticmethod
    def _engagement_port():
        from components.agents.infrastructure.repositories.agent_engagement_repository import (
            OrmAgentEngagementRepository,
        )

        return OrmAgentEngagementRepository()

    @staticmethod
    def build_follow_agent_use_case() -> FollowAgentUseCase:
        return FollowAgentUseCase(port=AIProvider._engagement_port())

    @staticmethod
    def build_unfollow_agent_use_case() -> UnfollowAgentUseCase:
        return UnfollowAgentUseCase(port=AIProvider._engagement_port())

    @staticmethod
    def build_like_agent_use_case() -> LikeAgentUseCase:
        return LikeAgentUseCase(port=AIProvider._engagement_port())

    @staticmethod
    def build_unlike_agent_use_case() -> UnlikeAgentUseCase:
        return UnlikeAgentUseCase(port=AIProvider._engagement_port())

    @staticmethod
    def build_rate_agent_use_case() -> RateAgentUseCase:
        return RateAgentUseCase(port=AIProvider._engagement_port())

    @staticmethod
    def build_comment_agent_use_case() -> CommentAgentUseCase:
        return CommentAgentUseCase(port=AIProvider._engagement_port())

    @staticmethod
    def build_share_agent_use_case() -> ShareAgentUseCase:
        return ShareAgentUseCase(port=AIProvider._engagement_port())

    @staticmethod
    def build_revoke_share_use_case() -> RevokeShareUseCase:
        return RevokeShareUseCase(port=AIProvider._engagement_port())

    # ── Agent memory command use cases ────────────────────────────────

    @staticmethod
    def _memory_command_port():
        from components.agents.infrastructure.repositories.agent_memory_command_repository import (
            OrmAgentMemoryCommandRepository,
        )

        return OrmAgentMemoryCommandRepository()

    @staticmethod
    def build_clear_agent_memory_use_case() -> ClearAgentMemoryUseCase:
        return ClearAgentMemoryUseCase(port=AIProvider._memory_command_port())

    @staticmethod
    def build_add_system_message_use_case() -> AddAgentSystemMessageUseCase:
        return AddAgentSystemMessageUseCase(port=AIProvider._memory_command_port())

    # ── Teammate profile use cases ────────────────────────────────────

    @staticmethod
    def _teammate_profile_port():
        from components.agents.infrastructure.repositories.teammate_profile_repository import (
            OrmTeammateProfileRepository,
        )

        return OrmTeammateProfileRepository()

    @staticmethod
    def build_get_teammate_profile_use_case() -> GetTeammateProfileUseCase:
        return GetTeammateProfileUseCase(port=AIProvider._teammate_profile_port())

    @staticmethod
    def build_update_teammate_profile_use_case() -> UpdateTeammateProfileUseCase:
        return UpdateTeammateProfileUseCase(port=AIProvider._teammate_profile_port())

    # ── Queries (CQRS read side) ─────────────────────────────────────

    @staticmethod
    def build_workspace_search_query() -> WorkspaceSearchQuery:
        """Wire vector-store port into the workspace search query."""
        return WorkspaceSearchQuery(
            vector_store=AIVectorStoreProvider().get_port(),
        )

    @staticmethod
    def build_agent_graph_query() -> FetchAgentGraphQuery:
        from components.agents.infrastructure.repositories.agent_graph_query_repository import (
            OrmAgentGraphQueryRepository,
        )

        return FetchAgentGraphQuery(query_port=OrmAgentGraphQueryRepository())

    @staticmethod
    def build_execution_detail_query() -> FetchAgentExecutionDetailQuery:
        from components.agents.infrastructure.repositories.agent_execution_query_repository import (
            OrmAgentExecutionQueryRepository,
        )

        return FetchAgentExecutionDetailQuery(query_port=OrmAgentExecutionQueryRepository())

    @staticmethod
    def build_execution_list_query() -> FetchAgentExecutionListQuery:
        from components.agents.infrastructure.repositories.agent_execution_query_repository import (
            OrmAgentExecutionQueryRepository,
        )

        return FetchAgentExecutionListQuery(query_port=OrmAgentExecutionQueryRepository())

    @staticmethod
    def build_agent_memory_query() -> FetchAgentMemoryQuery:
        from components.agents.infrastructure.repositories.agent_execution_query_repository import (
            OrmAgentExecutionQueryRepository,
        )

        return FetchAgentMemoryQuery(query_port=OrmAgentExecutionQueryRepository())

    @staticmethod
    def _engagement_query_port():
        from components.agents.infrastructure.repositories.agent_engagement_query_repository import (
            OrmAgentEngagementQueryRepository,
        )

        return OrmAgentEngagementQueryRepository()

    @staticmethod
    def build_agent_ratings_query() -> FetchAgentRatingsQuery:
        return FetchAgentRatingsQuery(query_port=AIProvider._engagement_query_port())

    @staticmethod
    def build_agent_comments_query() -> FetchAgentCommentsQuery:
        return FetchAgentCommentsQuery(query_port=AIProvider._engagement_query_port())

    @staticmethod
    def build_shared_agent_query() -> FetchSharedAgentQuery:
        return FetchSharedAgentQuery(query_port=AIProvider._engagement_query_port())

    # ── Agent runtime ports (framework-swappable) ───────────────────

    @staticmethod
    def build_agent_runtime():
        """Return the agent runtime adapter (currently LangChain).

        To switch frameworks, swap this to return a LlamaIndex/CrewAI adapter.
        """
        from components.agents.infrastructure.adapters.langchain.runtime_adapter import (
            LangChainRuntimeAdapter,
        )

        return LangChainRuntimeAdapter()

    @staticmethod
    def build_agent_memory():
        """Return the agent memory adapter (currently LangChain).

        To switch frameworks, swap this to return a LlamaIndex adapter.
        """
        from components.agents.infrastructure.adapters.langchain.memory_adapter import (
            LangChainMemoryAdapter,
        )

        return LangChainMemoryAdapter()

    # `build_orchestration()` was removed when the legacy
    # `OrchestratorAgent` ReAct class was retired. Orchestration now
    # happens through the deep LangGraph pipeline accessed via
    # `AgentService.execute_agent` with `context["mode"] = "deep"`.
    # See `infrastructure/adapters/langchain/agents/ai_teammate_agent.py`
    # and `infrastructure/adapters/langchain/deep/`.

    # ── Infrastructure ports ──────────────────────────────────────────

    @staticmethod
    def build_artifact_store() -> ArtifactStorePort:
        """Return the artifact store adapter (ORM-backed)."""
        return OrmArtifactStoreAdapter()

    @staticmethod
    def build_tool_registry() -> ToolRegistryPort:
        """Return the detector/tool registry adapter."""
        return DetectorRegistryAdapter()

    # ── Cross-context query ports ─────────────────────────────────────

    @staticmethod
    def build_conversation_repository():
        from components.agents.infrastructure.repositories.orm_conversation_repository import (
            OrmConversationRepository,
        )

        return OrmConversationRepository()

    @staticmethod
    def build_conversation_message_repository():
        from components.agents.infrastructure.repositories.orm_conversation_repository import (
            OrmConversationMessageRepository,
        )

        return OrmConversationMessageRepository()

    @staticmethod
    def build_workspace_query():
        from components.agents.infrastructure.repositories.orm_cross_context_repository import (
            OrmWorkspaceQueryAdapter,
        )

        return OrmWorkspaceQueryAdapter()

    @staticmethod
    def build_team_query():
        from components.agents.infrastructure.repositories.orm_cross_context_repository import (
            OrmTeamQueryAdapter,
        )

        return OrmTeamQueryAdapter()

    @staticmethod
    def build_project_query():
        from components.agents.infrastructure.repositories.orm_cross_context_repository import (
            OrmProjectQueryAdapter,
        )

        return OrmProjectQueryAdapter()

    @staticmethod
    def build_user_query():
        from components.agents.infrastructure.repositories.orm_cross_context_repository import (
            OrmUserQueryAdapter,
        )

        return OrmUserQueryAdapter()

    @staticmethod
    def build_file_repository():
        from components.agents.infrastructure.repositories.orm_cross_context_repository import (
            OrmFileRepositoryAdapter,
        )

        return OrmFileRepositoryAdapter()

    @staticmethod
    def build_document_query():
        from components.agents.infrastructure.repositories.orm_cross_context_repository import (
            OrmDocumentQueryAdapter,
        )

        return OrmDocumentQueryAdapter()

    # ── Tool data repositories (cross-context) ─────────────────────────

    @staticmethod
    def build_project_tool_repository():
        from components.agents.infrastructure.repositories.tool_data_repository import OrmProjectToolRepository

        return OrmProjectToolRepository()

    @staticmethod
    def build_task_tool_repository():
        from components.agents.infrastructure.repositories.tool_data_repository import OrmTaskToolRepository

        return OrmTaskToolRepository()

    @staticmethod
    def build_workspace_tool_repository():
        from components.agents.infrastructure.repositories.tool_data_repository import OrmWorkspaceToolRepository

        return OrmWorkspaceToolRepository()

    @staticmethod
    def build_user_tool_repository():
        from components.agents.infrastructure.repositories.tool_data_repository import OrmUserToolRepository

        return OrmUserToolRepository()

    @staticmethod
    def build_permission_tool_repository():
        from components.agents.infrastructure.repositories.tool_data_repository import OrmPermissionToolRepository

        return OrmPermissionToolRepository()

    # ── Framework-decoupling ports ────────────────────────────────────

    @staticmethod
    def build_llm_provider():
        """Return the LLM provider port (wraps LLMFactory).

        Adapters call this instead of importing LLMFactory directly.
        """
        from components.agents.infrastructure.adapters.llm_provider_adapter import (
            LLMFactoryAdapter,
        )

        return LLMFactoryAdapter()

    @staticmethod
    def build_agent_permission():
        """Return the agent permission port (wraps ai_can / ensure_* facades).

        Adapters call this instead of importing application facades directly.
        """
        from components.agents.infrastructure.adapters.agent_permission_adapter import (
            AgentPermissionAdapter,
        )

        return AgentPermissionAdapter()
