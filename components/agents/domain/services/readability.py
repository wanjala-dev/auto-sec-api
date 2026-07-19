"""Deterministic readability scoring — Flesch Reading Ease + grade level.

A pure, dependency-free text-quality domain service (sibling to
``faithfulness_verifier``). Used by the writing-eval harness to score how
accessible generated copy is, and reusable by a future runtime
reading-level linter. No framework imports.

Flesch Reading Ease (higher = easier; ~60–70 is "plain English"):
    206.835 − 1.015 × (words/sentences) − 84.6 × (syllables/words)

Flesch–Kincaid Grade (US school grade level; lower = more accessible):
    0.39 × (words/sentences) + 11.8 × (syllables/words) − 15.59

Syllable counting uses a vowel-group heuristic — not perfect, but stable
and good enough to track relative readability across prompt iterations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_SENTENCE_RE = re.compile(r"[.!?]+")
_TAG_RE = re.compile(r"<[^>]+>")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")


@dataclass(frozen=True)
class ReadabilityScore:
    """Readability metrics for a block of prose."""

    flesch_reading_ease: float
    flesch_kincaid_grade: float
    word_count: int
    sentence_count: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "flesch_reading_ease": round(self.flesch_reading_ease, 1),
            "flesch_kincaid_grade": round(self.flesch_kincaid_grade, 1),
            "word_count": self.word_count,
            "sentence_count": self.sentence_count,
        }


def strip_html(text: str) -> str:
    """Drop tags so readability scores the prose, not the markup."""
    return _TAG_RE.sub(" ", text or "")


def count_syllables(word: str) -> int:
    """Heuristic syllable count for one word (minimum 1)."""
    word = word.lower()
    groups = _VOWEL_GROUP_RE.findall(word)
    count = len(groups)
    # Silent trailing 'e' (e.g. "make") usually isn't its own syllable,
    # but words like "the" must keep a floor of 1.
    if word.endswith("e") and count > 1 and not word.endswith("le"):
        count -= 1
    return max(1, count)


def score_readability(text: str) -> ReadabilityScore:
    """Compute Flesch metrics for ``text`` (HTML or plain)."""
    plain = strip_html(text)
    words = _WORD_RE.findall(plain)
    word_count = len(words)
    # At least one sentence so we never divide by zero; a wall of text
    # with no terminal punctuation still counts as one long sentence.
    sentence_count = max(1, len(_SENTENCE_RE.findall(plain)))

    if word_count == 0:
        # Empty copy: worst readability, highest grade — the grader
        # turns this into a failing score.
        return ReadabilityScore(
            flesch_reading_ease=0.0,
            flesch_kincaid_grade=20.0,
            word_count=0,
            sentence_count=sentence_count,
        )

    syllables = sum(count_syllables(w) for w in words)
    words_per_sentence = word_count / sentence_count
    syllables_per_word = syllables / word_count

    ease = 206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word
    grade = 0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59

    return ReadabilityScore(
        flesch_reading_ease=ease,
        flesch_kincaid_grade=grade,
        word_count=word_count,
        sentence_count=sentence_count,
    )
