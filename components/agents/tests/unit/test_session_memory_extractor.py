"""Unit tests for session memory extraction domain service."""

from components.agents.domain.services.session_memory_extractor import (
    ExtractedFact,
    SessionMemory,
    build_extraction_prompt,
)


class TestExtractedFact:
    def test_create(self):
        fact = ExtractedFact.create(
            content="User prefers CSV exports",
            category="preference",
            confidence=0.9,
            source_conversation_id="conv-123",
        )
        assert fact.content == "User prefers CSV exports"
        assert fact.category == "preference"
        assert fact.confidence == 0.9
        assert fact.fact_id is not None


class TestSessionMemory:
    def test_empty_memory(self):
        memory = SessionMemory(workspace_id="ws-1", agent_type="workspace_agent")
        assert memory.fact_count == 0
        assert memory.as_context_string() == ""

    def test_context_string(self):
        facts = [
            ExtractedFact.create(content="Budget is $50k", category="context"),
            ExtractedFact.create(content="Prefers weekly reports", category="preference"),
        ]
        memory = SessionMemory(
            workspace_id="ws-1",
            agent_type="budget_agent",
            facts=facts,
        )
        ctx = memory.as_context_string()
        assert "Budget is $50k" in ctx
        assert "Prefers weekly reports" in ctx
        assert "## Remembered context" in ctx

    def test_max_facts_limit(self):
        facts = [
            ExtractedFact.create(content=f"Fact {i}", category="context")
            for i in range(30)
        ]
        memory = SessionMemory(workspace_id="ws-1", agent_type="test", facts=facts)
        ctx = memory.as_context_string(max_facts=5)
        assert ctx.count("- [context]") == 5


class TestBuildExtractionPrompt:
    def test_prompt_contains_conversation(self):
        prompt = build_extraction_prompt("User: Hello\nAssistant: Hi there!")
        assert "User: Hello" in prompt
        assert "JSON array" in prompt
