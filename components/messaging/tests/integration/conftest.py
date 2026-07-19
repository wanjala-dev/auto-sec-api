"""Shared fixtures for messaging integration tests.

Builds two users who share a workspace (Alice owns it, Bob is an active
member) plus an outsider (Carol) who shares nothing — the setup the
shared-workspace DM gate is checked against.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from infrastructure.persistence.workspaces.models import WorkspaceMembership


@pytest.fixture
def alice(user_factory):
    return user_factory(username="alice", email="alice@example.com")


@pytest.fixture
def bob(user_factory):
    return user_factory(username="bob", email="bob@example.com")


@pytest.fixture
def carol(user_factory):
    """An outsider who shares no workspace with Alice or Bob."""
    return user_factory(username="carol", email="carol@example.com")


@pytest.fixture
def shared_workspace(workspace_factory, alice, bob):
    """Alice owns the workspace; Bob is an ACTIVE member — so they share it."""
    ws = workspace_factory(owner=alice)
    WorkspaceMembership.objects.create(workspace=ws, user=bob)
    return ws


@pytest.fixture
def add_member(shared_workspace):
    """Add another ACTIVE member to the shared workspace and return them."""

    def _add(user):
        WorkspaceMembership.objects.create(workspace=shared_workspace, user=user)
        return user

    return _add


@pytest.fixture
def client_for():
    """Return a factory producing an authenticated APIClient for a user."""

    def _client(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _client


@pytest.fixture
def png_upload():
    """A tiny valid PNG as an uploaded file (Pillow-decodable)."""
    from io import BytesIO

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile("attach.png", buf.read(), content_type="image/png")
