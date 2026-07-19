"""End-to-end prompt-eval tests that drive the harness against datasets.

These are intentionally separate from ``components/agents/tests/unit/``
because they involve LLM calls (paid + non-deterministic) and run
under a different policy: scores are informational, not blocking.
"""
