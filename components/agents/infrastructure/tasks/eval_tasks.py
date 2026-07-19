"""Scheduled reviewer-feedback eval task (SEE-191, Phase 6d).

Runs the ``run_feedback_eval`` management command on a weekly Beat cadence so the
writing-quality rubric is re-scored against the accumulated reviewer-feedback
snapshots without an operator shelling onto the box. The command already
isolates each artifact type in its own try/except, so one type failing (e.g. a
flaky LLM judge) does not abort the rest; this task simply drives it and logs
the lifecycle.

The command hits a real LLM (the ``WritingJudge``), so this is a low-frequency
scheduled task, not a per-request path.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(name="agents.run_reviewer_feedback_eval", ignore_result=True)
def run_reviewer_feedback_eval() -> None:
    """Re-score the reviewer-feedback datasets against the writing rubric."""
    logger.info("agents.run_reviewer_feedback_eval started")
    call_command("run_feedback_eval")
    logger.info("agents.run_reviewer_feedback_eval completed")
