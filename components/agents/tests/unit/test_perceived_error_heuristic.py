"""SEE-205 — perceived-error transcript heuristic (pure).

High precision: clear rebuttals and pasted errors flag; benign questions and
non-rebuttal replies do not; a rebuttal only counts when it follows an assistant
answer.
"""

from __future__ import annotations

import pytest

from components.agents.domain.detectors.perceived_error import (
    classify_perceived_error,
    detect_perceived_errors,
)

REBUTTALS = [
    "That's wrong.",
    "that is incorrect",
    "No, that's not right.",
    "you're wrong about that",
    "That didn't work.",
    "it doesn't work",
    "that's not what I asked for",
    "still broken",
    "that's not helpful",
    "wrong answer, try again",
]

BENIGN = [
    "Thanks, that's perfect!",
    "How do I fix a KeyError in Python?",  # asks about an error, not a rebuttal
    "Can you also add the totals?",
    "Great, what's next?",
    "",
    "   ",
]


class TestClassify:
    @pytest.mark.parametrize("text", REBUTTALS)
    def test_flags_rebuttals(self, text):
        assert classify_perceived_error(text) is not None

    @pytest.mark.parametrize("text", BENIGN)
    def test_ignores_benign(self, text):
        assert classify_perceived_error(text) is None

    def test_flags_pasted_traceback(self):
        pasted = "Traceback (most recent call last):\n  File x\nValueError: bad"
        assert classify_perceived_error(pasted) == "user pasted an error back"


class TestDetectPerceivedErrors:
    def test_flags_user_rebuttal_after_assistant(self):
        messages = [
            {"role": "user", "content": "What's our donor total?"},
            {"role": "assistant", "content": "It is $500."},
            {"role": "user", "content": "That's wrong, it's $5,000."},
        ]

        flagged = detect_perceived_errors(messages)

        assert len(flagged) == 1
        assert flagged[0].index == 2
        assert "500" in flagged[0].assistant_snippet

    def test_rebuttal_not_following_assistant_is_ignored(self):
        # Two user messages in a row — the second is not rebutting an answer.
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "user", "content": "that's wrong"},
        ]

        assert detect_perceived_errors(messages) == []

    def test_clean_conversation_flags_nothing(self):
        messages = [
            {"role": "user", "content": "What's our donor total?"},
            {"role": "assistant", "content": "It is $5,000."},
            {"role": "user", "content": "Perfect, thanks!"},
        ]

        assert detect_perceived_errors(messages) == []
