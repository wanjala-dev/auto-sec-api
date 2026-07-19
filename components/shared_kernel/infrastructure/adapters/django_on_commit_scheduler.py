"""Driven adapter: ``OnCommitScheduler`` backed by Django's transaction hook.

Single legal touchpoint between application-layer post-commit
scheduling and Django's ``transaction.on_commit``.
"""

from __future__ import annotations

from typing import Callable

from django.db import transaction


def django_on_commit_scheduler(callback: Callable[[], None]) -> None:
    """Schedule ``callback`` after the surrounding transaction commits."""
    transaction.on_commit(callback)
