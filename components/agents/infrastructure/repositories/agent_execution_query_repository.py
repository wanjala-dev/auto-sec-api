"""ORM adapter for agent execution read queries.

Extracted from get_agent_execution() and list_agent_executions() in agents_controller.py.
"""
from __future__ import annotations

from typing import Any

from components.agents.domain.errors import DomainError
from components.agents.application.ports.agent_execution_query_port import (
    AgentExecutionQueryPort,
    AgentMemoryData,
    AgentMemoryRequest,
    ConversationPagination,
    ExecutionDetailData,
    ExecutionDetailRequest,
    ExecutionListData,
    ExecutionListRequest,
)


class _AgentNotFoundError(DomainError, LookupError):
    """Agent or execution not found."""


class OrmAgentExecutionQueryRepository(AgentExecutionQueryPort):

    def fetch_execution_detail(self, *, request: ExecutionDetailRequest) -> ExecutionDetailData:
        from infrastructure.persistence.ai.agents.models import AgentExecution
        from components.agents.infrastructure.services.agents_service import get_agent_service

        try:
            execution = AgentExecution.objects.select_related("agent").get(id=request.execution_id)
        except AgentExecution.DoesNotExist:
            raise _AgentNotFoundError("Execution not found")

        data = ExecutionDetailData(
            execution_id=execution.id,
            agent_id=str(execution.agent.agent_id),
            agent_record=execution.agent,
            task_id=execution.task_id,
            status=execution.status,
            success=execution.success,
            progress=execution.progress,
            state=execution.state,
            result=execution.result,
            error_message=execution.error_message,
            created_at=execution.created_at.isoformat() if execution.created_at else None,
            updated_at=execution.updated_at.isoformat() if execution.updated_at else None,
        )

        # Fetch conversation history from memory service
        try:
            factory = get_agent_service()
            memory_service = factory.get_agent_memory_service(str(execution.agent.agent_id))
            conversation_id = memory_service.get_conversation_id()

            history = memory_service.get_conversation_history(
                limit=request.limit,
                offset=request.offset,
                order=request.order,
            )
            total_messages = memory_service.get_memory_stats().get("total_messages", 0)
            returned = len(history)
            has_more = (
                request.limit is not None
                and total_messages is not None
                and (request.offset + returned) < total_messages
            )

            data.conversation_id = conversation_id
            data.conversation_messages = history
            data.conversation_pagination = ConversationPagination(
                limit=request.limit,
                offset=request.offset,
                order=request.order,
                total=total_messages,
                returned=returned,
                has_more=has_more,
                next_offset=(request.offset + returned) if has_more else None,
            )
        except Exception:
            data.conversation_id = None
            data.conversation_messages = []
            data.conversation_pagination = ConversationPagination()

        return data

    def fetch_execution_list(self, *, request: ExecutionListRequest) -> ExecutionListData:
        from infrastructure.persistence.ai.agents.models import Agent, AgentExecution

        try:
            agent_record = Agent.objects.select_related("workspace").get(agent_id=request.agent_id)
        except Agent.DoesNotExist:
            raise _AgentNotFoundError("Agent not found")

        ordering = "created_at" if request.order == "asc" else "-created_at"
        queryset = AgentExecution.objects.filter(
            agent__agent_id=request.agent_id,
        ).order_by(ordering)

        total = queryset.count()
        if request.offset:
            queryset = queryset[request.offset:]
        if request.limit is not None:
            queryset = queryset[: request.limit]

        executions = []
        for execution in queryset:
            payload: dict[str, Any] = {
                "execution_id": execution.id,
                "agent_id": str(execution.agent.agent_id),
                "query": execution.query,
                "result": execution.result,
                "status": execution.status,
                "success": execution.success,
                "progress": execution.progress,
                "task_id": execution.task_id,
                "error_message": execution.error_message,
                "created_at": execution.created_at.isoformat() if execution.created_at else None,
                "updated_at": execution.updated_at.isoformat() if execution.updated_at else None,
            }
            if request.include_state:
                payload["state"] = execution.state
            executions.append(payload)

        returned = len(executions)
        has_more = request.limit is not None and (request.offset + returned) < total

        return ExecutionListData(
            agent_id=str(agent_record.agent_id),
            agent_record=agent_record,
            executions=executions,
            total=total,
            has_more=has_more,
            returned=returned,
            next_offset=(request.offset + returned) if has_more else None,
        )

    def fetch_agent_memory(self, *, request: AgentMemoryRequest) -> AgentMemoryData:
        from infrastructure.persistence.ai.agents.models import Agent, AgentExecution
        from components.agents.infrastructure.services.agents_service import get_agent_service

        try:
            agent_record = Agent.objects.select_related("workspace").get(agent_id=request.agent_id)
        except Agent.DoesNotExist:
            raise _AgentNotFoundError("Agent not found")

        factory = get_agent_service()
        memory_service = factory.get_agent_memory_service(str(agent_record.agent_id))

        memory_stats = memory_service.get_memory_stats()
        conversation_history = memory_service.get_conversation_history(
            limit=request.limit,
            offset=request.offset,
            order=request.order,
        )

        # Latest execution
        last_execution = None
        try:
            last_exec_obj = (
                AgentExecution.objects.filter(agent__agent_id=request.agent_id)
                .order_by("-created_at")
                .first()
            )
            if last_exec_obj:
                last_execution = {
                    "execution_id": last_exec_obj.id,
                    "status": last_exec_obj.status,
                    "success": last_exec_obj.success,
                    "progress": last_exec_obj.progress,
                    "task_id": last_exec_obj.task_id,
                    "result": last_exec_obj.result,
                    "error_message": last_exec_obj.error_message,
                    "created_at": last_exec_obj.created_at.isoformat() if last_exec_obj.created_at else None,
                    "updated_at": last_exec_obj.updated_at.isoformat() if last_exec_obj.updated_at else None,
                }
        except Exception:
            last_execution = None

        last_progress = last_execution["progress"] if isinstance(last_execution, dict) else None

        total_messages = memory_stats.get("total_messages") if isinstance(memory_stats, dict) else None
        returned = len(conversation_history)
        has_more = (
            request.limit is not None
            and total_messages is not None
            and (request.offset + returned) < total_messages
        )

        return AgentMemoryData(
            agent_id=request.agent_id,
            agent_record=agent_record,
            memory_stats=memory_stats,
            conversation_history=conversation_history,
            last_execution=last_execution,
            last_progress=last_progress,
            pagination=ConversationPagination(
                limit=request.limit,
                offset=request.offset,
                order=request.order,
                total=total_messages or 0,
                returned=returned,
                has_more=has_more,
                next_offset=(request.offset + returned) if has_more else None,
            ),
        )
