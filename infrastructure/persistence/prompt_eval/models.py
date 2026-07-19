"""``PromptEvalExample`` — a labeled eval case grown from a reviewer decision.

Phase 6c of the Verification-Assisted Sign-Off Spine (SEE-190). Each row is one
human sign-off decision (request-changes / reject / careful RED-band approve) on
an AI-generated artifact, turned into a durable eval example the content
generators can be measured against. The pure-domain twin is
``components.agents.domain.value_objects.eval_example.EvalExample``; the mapping
between the two lives in ``DjangoEvalExampleRepository``.

Idempotency is enforced at the schema level: a ``(artifact_type, artifact_id,
feedback_decision)`` triple is unique, so replaying the same
``SignOffDecisionRecorded`` event (Celery retry, at-least-once delivery) writes
nothing new.

``reviewer_id`` / ``workspace_id`` are stored as plain strings (no FK to the
user or workspace tables) — this is an eval-dataset side table, not an
operational one, and keeping it FK-free avoids a cross-app cascade coupling the
dataset's lifetime to a user/workspace row.
"""

from __future__ import annotations

from django.db import models


class PromptEvalExample(models.Model):
    """One labeled eval case derived from a reviewer sign-off decision."""

    # Dataset / case identity
    dataset_name = models.CharField(max_length=255, db_index=True)
    case_id = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    goal = models.TextField()
    # Eval payload
    input_data = models.JSONField(default=dict)
    expected_output = models.JSONField(default=dict)
    source_type = models.CharField(max_length=32, default="sign_off_feedback")
    # Feedback label + provenance
    feedback_decision = models.CharField(max_length=32)
    feedback_codes = models.JSONField(default=list)
    feedback_note = models.TextField(blank=True)
    risk_band = models.CharField(max_length=16, blank=True)
    artifact_type = models.CharField(max_length=64)
    artifact_id = models.CharField(max_length=64)
    reviewer_id = models.CharField(max_length=64, blank=True)
    workspace_id = models.CharField(max_length=64, blank=True, db_index=True)
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("artifact_type", "artifact_id", "feedback_decision")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.dataset_name}:{self.case_id} [{self.feedback_decision}]"
