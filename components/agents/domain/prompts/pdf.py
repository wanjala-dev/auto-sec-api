"""
PDF Prompt Builders
Centralized prompt constructors for PDF Q&A and summarization so all PDF endpoints
reuse consistent instructions and tone.
"""
from typing import Optional


def build_pdf_qa_prompt(
    history_context: str,
    context: str,
    pdf_id: str,
    input_text: str,
    system_preamble: Optional[str] = None,
) -> str:
    """Construct a prompt for conversational PDF Q&A.

    Args:
        history_context: Prior dialog formatted as lines (Human:/Assistant:)
        context: Extracted relevant PDF snippets
        pdf_id: Document identifier for user reference
        input_text: The user's question
        system_preamble: Optional preamble to adjust tone/policy

    Returns:
        Prompt string
    """
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
    """Construct a prompt to summarize PDF content.

    Args:
        full_content: Concatenated relevant text chunks
        max_length: Target word length of the summary

    Returns:
        Prompt string
    """
    return (
        "Please provide a comprehensive summary of the following PDF content. "
        f"The summary should be approximately {max_length} words and cover the main topics, "
        "key points, and important information.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Summary:"
    )


# Additional reusable PDF prompt builders

def build_pdf_bullet_summary_prompt(full_content: str, bullets: int = 5) -> str:
    """Ask for a concise, bullet-point summary."""
    return (
        f"Summarize the following PDF content into {bullets} concise bullet points. "
        "Focus on the most important takeaways.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Bullet Summary:"
    )


def build_pdf_outline_prompt(full_content: str, depth: int = 2) -> str:
    """Request an outline with sections and subsections up to a specified depth."""
    return (
        "Create a structured outline of the following content. "
        f"Include headings up to depth {depth} (e.g., 1., 1.1, 1.2).\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Outline:"
    )


def build_pdf_key_points_prompt(full_content: str, count: int = 10) -> str:
    """Extract a fixed number of key points."""
    return (
        f"List the top {count} key points from the following content. "
        "Be specific and avoid redundancy.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Key Points:"
    )


def build_pdf_glossary_prompt(full_content: str, terms_count: int = 15) -> str:
    """Build a glossary of important terms and definitions."""
    return (
        f"Create a glossary of up to {terms_count} important terms from the content. "
        "For each term, provide a one-sentence definition.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Glossary (term — definition):"
    )


def build_pdf_explain_for_audience_prompt(
    full_content: str,
    audience: str = "non-technical audience",
    length: str = "short",
) -> str:
    """Explain the content tailored to a specific audience and length."""
    return (
        f"Explain the following content for a {audience}. "
        f"Provide a {length} explanation and avoid jargon.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Explanation:"
    )


def build_pdf_flashcards_prompt(full_content: str, cards: int = 10) -> str:
    """Generate Q&A flashcards for study."""
    return (
        f"Generate {cards} high-quality Q&A flashcards from the content. "
        "Each flashcard should have a clear question and a concise answer.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Flashcards (Q: ... A: ...):"
    )


def build_pdf_action_items_prompt(full_content: str, role: Optional[str] = None) -> str:
    """Extract actionable next steps; optionally tailor to a role (e.g., 'project manager')."""
    target = f" for a {role}" if role else ""
    return (
        f"From the following content, extract actionable next steps{target}. "
        "Include owners (if inferable), due dates (if mentioned), and dependencies.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Action Items:"
    )


def build_pdf_question_generation_prompt(full_content: str, questions: int = 10, difficulty: str = "mixed") -> str:
    """Generate comprehension questions at a target difficulty (easy/medium/hard/mixed)."""
    return (
        f"Create {questions} {difficulty} comprehension questions based on the content. "
        "Provide an answer key at the end.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Questions:"
    )


def build_pdf_compare_sections_prompt(context_a: str, context_b: str, aspect: str = "differences") -> str:
    """Compare two sections (e.g., differences, similarities, pros/cons)."""
    return (
        f"Compare the following two sections focusing on {aspect}. "
        "Be concise and structured.\n\n"
        f"Section A:\n{context_a}\n\n"
        f"Section B:\n{context_b}\n\n"
        "Comparison:"
    )


def build_pdf_translate_prompt(full_content: str, target_lang: str = "French", tone: str = "neutral") -> str:
    """Translate content to a target language with a desired tone."""
    return (
        f"Translate the following content into {target_lang} with a {tone} tone. "
        "Preserve meaning and key details.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Translation:"
    )


def build_pdf_citations_prompt(full_content: str) -> str:
    """Extract references/citations and any URLs mentioned."""
    return (
        "Extract any references or citations (authors, titles, years) and URLs present in the content.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Citations/References:"
    )


def build_pdf_tldr_prompt(full_content: str, words: int = 100) -> str:
    """Ask for an ultra-brief summary (TL;DR)."""
    return (
        f"Provide a TL;DR (about {words} words) for the content below.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "TL;DR:"
    )


def build_pdf_section_summary_prompt(section_title: str, section_content: str, words: int = 200) -> str:
    """Summarize a single section by title with a word budget."""
    return (
        f"Summarize the section '{section_title}' in about {words} words.\n\n"
        f"Section Content:\n{section_content}\n\n"
        "Summary:"
    )


def build_pdf_table_extraction_prompt(full_content: str, schema_description: Optional[str] = None) -> str:
    """Request structured extraction for tabular data when present.

    Note: This guides an LLM to extract structured rows; real table extraction is best
    done via a table parser when possible.
    """
    schema = (
        f"Use this JSON schema for rows: {schema_description}. " if schema_description else ""
    )
    return (
        f"Extract any tabular data present from the content below. {schema}"
        "Return a JSON array of rows; omit if none.\n\n"
        f"PDF Content:\n{full_content}\n\n"
        "Rows (JSON):"
    )
