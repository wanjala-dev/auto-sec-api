"""Driven adapter: ``UserLookupPort`` backed by Django's auth User model."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model


class DjangoUserLookupAdapter:
    def find_by_id(self, user_id: Any) -> Any | None:
        User = get_user_model()
        return User.objects.filter(id=user_id).first()
