"""Pure prompt builders for PDF Q&A and summarization.

Mirrors the public API of ``apps.ai.prompts.pdf`` but lives in the domain
layer so that application use cases can import without violating the
framework-free guardrail.  All functions are pure — no I/O, no framework deps.
"""

from __future__ import annotations

from typing import Optional


def build_pdf_qa_prompt(
    history_context: str,
    context: str,
    pdf_id: str,
    input_text: str,
    system_preamble: Optional[str] = None,
) -> str:
    """Construct a prompt for conversational PDF Q&A."""
    preface = system_preamble or (
        "You are a helpful assistant that answers questions based on PDF content. "
        "Use the provided context and conversation history to craft accurate, concise answers. "
        "When referring to people in the document, use their actual names rather than generic terms like 'the speaker' or 'the author'."
    )
    return (
        f"{preface}\n\n"
        f"Previous conversation:\n{history_context or 'No previous conversation.'}\n\n"
        f"Current context from PDF {pdf_id}:\n{context}\n\n"
        f"Current User Question: {input_text}\n\n"
        "If the context doesn't contain enough information to answer the question, "
        "say so explicitly and suggest what additional information might be needed."
    )


def build_pdf_summary_prompt(full_content: str, max_length: int = 500) -> str:
    """Construct a prompt to summarize PDF content."""
    return (
        "Please provide a comprehensive summary of the following PDF content. "
        f"The summary should be approximately {max_length} words and cover the main topics, "
        "key points, and important information.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Summary:"
    )


def build_pdf_tldr_prompt(full_content: str, words: int = 100) -> str:
    """Ask for an ultra-brief summary (TL;DR)."""
    return (
        f"Provide a TL;DR (about {words} words) for the content below.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "TL;DR:"
    )
