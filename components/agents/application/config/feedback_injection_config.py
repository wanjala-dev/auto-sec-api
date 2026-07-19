"""Configuration for reviewer-feedback few-shot injection (SEE-191, Phase 6d).

The "close the feedback loop" payoff: before a writing generator drafts an
artifact, we surface the reviewer counter-examples (recent CHANGES_REQUESTED /
REJECTED decisions on the same artifact type in the same workspace) so the model
can avoid repeating the mistakes a human already flagged.

Kept as plain module constants — simple, importable from the pure application
layer (no Django), and trivially monkeypatchable in tests. A per-workspace
override (some orgs want a bigger/smaller window, or to opt out) is a documented
follow-on, NOT this slice.

- ``FEEDBACK_FEW_SHOT_ENABLED`` — master switch. When ``False`` the use case
  returns ``""`` and generation runs on the un-augmented prompt.
- ``FEEDBACK_FEW_SHOT_MAX`` — how many recent negatives to inject at most. Small
  by design: a handful of concrete "don't do this" examples steers far better
  than a wall of them, and keeps the prompt token budget in check.
- ``FEEDBACK_FEW_SHOT_MAX_NOTE_CHARS`` — per-example note truncation. We inject
  the reviewer's *codes + note* (what they said was wrong), never the full
  rejected content — that would balloon the prompt and risk the model copying
  the very copy that got rejected.
"""

from __future__ import annotations

FEEDBACK_FEW_SHOT_ENABLED = True
FEEDBACK_FEW_SHOT_MAX = 3
FEEDBACK_FEW_SHOT_MAX_NOTE_CHARS = 280
