"""Backfill the AiActionDailyRollup read model from retained raw rows.

Runs the same recompute the ``ai.rollup_ai_action_daily`` beat task uses
(idempotent — re-running converges on the same numbers), widened to the
last N days and including the current partial day so a fresh install has
a today series immediately.

Usage:
    python manage.py backfill_ai_action_rollups --days 30
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Backfill AiActionDailyRollup rows for the last N days (including today)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="How many days back to recompute, counting today (default 30).",
        )

    def handle(self, *args, **options):
        from components.agents.infrastructure.tasks.ai_action_rollup_tasks import (
            rollup_ai_action_daily,
        )

        days = max(1, int(options["days"]))
        written = rollup_ai_action_daily(days_back=days, include_today=True)
        self.stdout.write(self.style.SUCCESS(f"Recomputed {days} day(s); wrote {written} rollup row(s)."))
