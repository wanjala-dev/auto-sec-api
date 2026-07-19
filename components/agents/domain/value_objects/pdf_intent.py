"""Pure domain logic for detecting user intent in PDF conversations.

No framework imports — just string analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

_SUMMARY_KEYWORDS = frozenset({
    "tldr", "summary", "summarize", "summarise",
    "summery", "summerize", "overview", "brief",
})

_STOP_WORDS = frozenset({
    "the", "and", "or", "but", "for", "with", "from", "about",
    "what", "who", "where", "when", "why", "how",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can", "must", "shall",
})


@dataclass(frozen=True)
class PdfIntent:
    kind: str  # "tldr", "summary", "qa"


def detect_pdf_intent(query: str) -> PdfIntent:
    """Classify a user query as tldr, summary, or general Q&A."""
    lower = query.lower().strip()
    if "tldr" in lower:
        return PdfIntent(kind="tldr")
    if any(kw in lower for kw in _SUMMARY_KEYWORDS):
        return PdfIntent(kind="summary")
    return PdfIntent(kind="qa")


def extract_search_words(query: str) -> list[str]:
    """Return non-trivial words from *query* for fallback retrieval."""
    return [
        word.strip()
        for word in query.split()
        if len(word.strip()) > 2 and word.strip().lower() not in _STOP_WORDS
    ]
