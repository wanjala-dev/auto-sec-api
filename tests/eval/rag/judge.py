"""LLM-as-judge protocol + caching wrapper for the RAG eval harness.

The four RAGAS-style metrics each call out to an LLM judge:
* Faithfulness   — extract claims, judge each against context
* Answer Relevancy — score answer-to-question alignment
* Context Precision — judge each chunk's relevance
* Context Recall is purely deterministic (no LLM call) — it's a set
  comparison against expected_sections, so it doesn't go through Judge.

`Judge` is a tiny protocol so tests can swap in a deterministic fake
without touching real LLMs. `CachedJudge` wraps any judge with a
content-addressed JSON cache so re-scoring an already-judged
(prompt_id, answer_hash) tuple is free.

The runner instantiates `OpenAIJudge` (or whichever provider's adapter
fits the configured judge_model) from our existing `AILlmProvider` port
— keeps the eval harness inside the same architecture rules.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True)
class JudgeRequest:
    """One judge call.

    `prompt_id` + `cache_key` together identify what's being judged;
    same (prompt_id, cache_key) on a future run returns the cached
    response instead of hitting the LLM again. `cache_key` is normally
    a hash of (system, user, model, temperature) so any change to the
    inputs invalidates the cache entry.
    """

    prompt_id: str
    system: str
    user: str
    cache_key: str


class Judge(Protocol):
    """Minimal interface: take a request, return the LLM's response text."""

    def call(self, request: JudgeRequest) -> str: ...


def _hash(*parts: str) -> str:
    """SHA-256 of the joined parts. Used to build cache_key inputs."""
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def build_cache_key(*, system: str, user: str, model: str, temperature: float) -> str:
    """Stable hash of the inputs that determine the LLM's response.

    Any change to system prompt / user prompt / model / temperature
    invalidates the cache. The eval set version is implicit via
    `user` because metric prompts encode the user content directly.
    """
    return _hash(system, user, model, f"{temperature:.3f}")


class CachedJudge:
    """Wraps any Judge with a JSON-on-disk cache.

    The cache is keyed by `(prompt_id, cache_key)` and stores raw LLM
    response text. Hit → return cached text. Miss → call wrapped
    judge, persist, return.

    Cache lives at `cache_path`; loaded lazily on first call and
    flushed after each miss so a killed run doesn't lose responses.
    """

    def __init__(self, wrapped: Judge, cache_path: Path):
        self._wrapped = wrapped
        self._path = cache_path
        self._loaded: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._loaded is not None:
            return self._loaded
        if self._path.exists():
            try:
                self._loaded = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # Corrupt cache file — start fresh rather than crashing
                # the eval. The miss path will rebuild.
                self._loaded = {}
        else:
            self._loaded = {}
        return self._loaded

    def _persist(self) -> None:
        if self._loaded is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._loaded, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def call(self, request: JudgeRequest) -> str:
        cache = self._load()
        key = f"{request.prompt_id}::{request.cache_key}"
        if key in cache:
            return cache[key]
        response = self._wrapped.call(request)
        cache[key] = response
        self._persist()
        return response


class StubJudge:
    """Deterministic judge for unit tests.

    Maps `cache_key` (or any input) to a canned response via the
    `responder` callable. Tests use this to exercise metric parsers
    without invoking real LLMs.
    """

    def __init__(self, responder: Callable[[JudgeRequest], str]):
        self._responder = responder

    def call(self, request: JudgeRequest) -> str:
        return self._responder(request)
