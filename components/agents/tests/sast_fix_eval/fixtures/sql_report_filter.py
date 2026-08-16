"""Frozen corpus source — ordinary VALUE interpolation (the positive control)."""

from django.db import connection


def findings_for_status(status: str, workspace_id: str) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT id, title FROM findings WHERE status = '{status}' AND workspace_id = '{workspace_id}'")
        return cursor.fetchall()
