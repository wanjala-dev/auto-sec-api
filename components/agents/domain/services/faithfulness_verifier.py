"""Deterministic faithfulness verifier (SEE-171).

Pure domain service — NO Django, NO ORM, NO LLM, NO infrastructure. It is
the "slot-and-verify" guard from the research synthesis
(``docs/plans/GROUNDED_CONTENT_GENERATION_2026-06-27.md`` §3): RAG alone
does not stop fabrication (15–30% persists), so after generation we
**regex-extract every money/quantity/date + proper noun from the produced
copy and assert each appears in the grounding context**. The single most
defensible square for AI fundraising copy is that we *verify* generated
figures against source data — no competitor does.

Stakes: a thank-you letter that invents a $50,000 grant amount, a funder
name, or a date is a trust catastrophe. This verifier makes
groundedness *enforceable* and *surfaceable* — it never silently strips,
it reports what could not be verified so the editor/reviewer (HITL) sees
a "review these unverified figures" signal.

Design choices (deliberate, documented):

- **Numbers/money/dates are flagged STRICTLY.** Every numeric token in the
  copy must have its numeric value present in the grounding context, or it
  lands in ``unsupported_numbers`` and flips ``ok`` to ``False``.
- **Proper names are flagged SOFTLY.** Multi-word capitalized phrases that
  aren't in the grounding context land in ``unsupported_names`` for human
  review, but they DO NOT flip ``ok`` — proper-noun extraction is
  heuristic and over-flagging real names (titles, salutations) would be
  noisy. ``ok`` is driven by numbers alone.

Comparison is value-based, not string-based: ``$50,000`` in the copy is
supported by ``50000`` (or ``50,000.00``) in the source. HTML tags and
entities are stripped before any extraction.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass

# ── HTML stripping ─────────────────────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# ── numeric tokens ─────────────────────────────────────────────────────────
# Display-form numeric mention: optional currency symbol prefix, the number,
# optional "%" or currency-code suffix. Used to produce readable report
# tokens; comparison is on the canonicalised numeric core only.
_NUMBER_TOKEN_RE = re.compile(
    r"(?P<pre>[$€£₦₹]\s?)?"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"(?P<post>\s?%|\s?(?:USD|EUR|GBP|KES|KSh|NGN|UGX|TZS|RWF|CAD|ZAR|GHS|USD)\b)?",
    re.IGNORECASE,
)
# Bare number core — used to harvest every numeric value from the grounding.
_NUMBER_CORE_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# ── proper nouns ───────────────────────────────────────────────────────────
# Two or more consecutive Capitalized words. Single capitalized words are
# never flagged (too noisy — sentence-initial words, "I", etc.).
_PROPER_NOUN_RE = re.compile(r"[A-Z][a-zA-Z.'’&-]*(?:\s+[A-Z][a-zA-Z.'’&-]*)+")

# Capitalized words that are common at sentence starts, salutations,
# closings, or as pronouns/connectors — stripped from the edges of a
# candidate phrase before deciding whether it's a real proper noun.
_NAME_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "of", "for", "to", "from",
        "with", "without", "in", "on", "at", "by", "as", "is", "are", "was",
        "were", "be", "been", "this", "that", "these", "those", "it", "we",
        "our", "you", "your", "i", "my", "they", "their", "he", "she", "his",
        "her", "dear", "hi", "hello", "hey", "thank", "thanks", "thankyou",
        "sincerely", "regards", "warmly", "best", "kind", "kindly", "yours",
        "cheers", "greetings", "welcome", "please", "subject", "re", "update",
        "here", "there", "today", "yesterday", "tomorrow", "now", "then",
        "when", "while", "because", "so", "if", "than", "also", "however",
        "meanwhile", "together", "over", "under", "about", "into", "onto",
        "upon", "per", "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday",
    }
)


@dataclass(frozen=True)
class FaithfulnessReport:
    """Result of a faithfulness check.

    Attributes:
        ok: ``True`` when no numeric/money/date token in the copy is
            unsupported by the grounding context. Proper-noun mismatches do
            NOT affect ``ok`` (they are advisory).
        unsupported_numbers: readable numeric tokens (e.g. ``"$50,000"``,
            ``"2026"``, ``"40%"``) present in the copy but absent from the
            grounding context.
        unsupported_names: multi-word proper-noun phrases present in the
            copy but absent from the grounding context — advisory only.
        checked: total number of distinct facts checked (numbers + names).
    """

    ok: bool
    unsupported_numbers: tuple[str, ...]
    unsupported_names: tuple[str, ...]
    checked: int

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "unsupported_numbers": list(self.unsupported_numbers),
            "unsupported_names": list(self.unsupported_names),
            "checked": self.checked,
        }


class FaithfulnessVerifier:
    """Deterministic, regex-based groundedness checker. Stateless."""

    def verify(
        self, *, generated_html: str, grounding_texts: list[str] | None
    ) -> FaithfulnessReport:
        """Check ``generated_html`` against the ``grounding_texts`` corpus.

        Args:
            generated_html: the produced copy (HTML or plain text). Tags and
                entities are stripped before extraction.
            grounding_texts: the source-of-truth strings the copy must be
                grounded in — retrieved RAG chunk contents plus any
                structured entity facts. ``None``/empty means *nothing* is
                supported (every figure becomes unsupported), which is the
                correct strict signal for ungrounded generation.

        Returns:
            A :class:`FaithfulnessReport`.
        """
        copy_text = self._strip_html(generated_html or "")
        corpus = self._strip_html(" ".join(grounding_texts or []))
        corpus_lower = corpus.lower()

        grounding_numbers = self._number_value_set(corpus)

        unsupported_numbers, checked_numbers = self._check_numbers(
            copy_text, grounding_numbers
        )
        unsupported_names, checked_names = self._check_names(
            copy_text, corpus_lower
        )

        return FaithfulnessReport(
            ok=not unsupported_numbers,
            unsupported_numbers=tuple(unsupported_numbers),
            unsupported_names=tuple(unsupported_names),
            checked=checked_numbers + checked_names,
        )

    # ── numbers ────────────────────────────────────────────────────────

    def _check_numbers(
        self, copy_text: str, grounding_numbers: set[str]
    ) -> tuple[list[str], int]:
        unsupported: list[str] = []
        seen: set[str] = set()
        checked = 0
        for match in _NUMBER_TOKEN_RE.finditer(copy_text):
            num = match.group("num")
            if num is None:
                continue
            canon = self._canon_number(num)
            if not canon:
                continue
            token = match.group(0).strip()
            if token in seen:
                continue
            seen.add(token)
            checked += 1
            if canon not in grounding_numbers:
                unsupported.append(token)
        return unsupported, checked

    def _number_value_set(self, text: str) -> set[str]:
        return {
            canon
            for raw in _NUMBER_CORE_RE.findall(text)
            if (canon := self._canon_number(raw))
        }

    @staticmethod
    def _canon_number(num: str) -> str:
        """Normalise a number to a comparable value string.

        ``50,000`` → ``50000``; ``50,000.00`` → ``50000``; ``1,200.50`` →
        ``1200.5``. Strips thousands separators and trailing fractional
        zeros so display variants compare equal.
        """
        s = num.replace(",", "")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s

    # ── proper nouns ───────────────────────────────────────────────────

    def _check_names(
        self, copy_text: str, corpus_lower: str
    ) -> tuple[list[str], int]:
        unsupported: list[str] = []
        seen: set[str] = set()
        checked = 0
        for match in _PROPER_NOUN_RE.finditer(copy_text):
            phrase = self._trim_stopwords(match.group(0))
            if phrase is None:
                continue
            key = phrase.lower()
            if key in seen:
                continue
            seen.add(key)
            checked += 1
            if not self._name_supported(phrase, corpus_lower):
                unsupported.append(phrase)
        return unsupported, checked

    @classmethod
    def _trim_stopwords(cls, phrase: str) -> str | None:
        """Strip leading/trailing stopwords; return the phrase only if at
        least two significant capitalized words remain. ``None`` means the
        candidate is not a flag-worthy proper noun (conservative)."""
        words = [w for w in _WS_RE.split(phrase.strip()) if w]
        while words and words[0].strip(".,'’&-").lower() in _NAME_STOPWORDS:
            words.pop(0)
        while words and words[-1].strip(".,'’&-").lower() in _NAME_STOPWORDS:
            words.pop()
        if len(words) < 2:
            return None
        return " ".join(words)

    @staticmethod
    def _name_supported(phrase: str, corpus_lower: str) -> bool:
        """A name is supported if the whole phrase appears in the corpus, or
        every one of its words appears somewhere in the corpus (lenient — we
        flag names softly to avoid false positives)."""
        key = phrase.lower()
        if key in corpus_lower:
            return True
        words = [w.strip(".,'’&-").lower() for w in _WS_RE.split(key) if w]
        return bool(words) and all(w and w in corpus_lower for w in words)

    # ── shared ─────────────────────────────────────────────────────────

    @staticmethod
    def _strip_html(value: str) -> str:
        without_tags = _TAG_RE.sub(" ", value or "")
        unescaped = _html.unescape(without_tags)
        return _WS_RE.sub(" ", unescaped).strip()
