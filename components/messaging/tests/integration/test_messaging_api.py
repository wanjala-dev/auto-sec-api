"""Messaging bounded-context HTTP integration tests.

Smokes the full request path for direct messaging as wired for GTM:
shared-workspace gating, text + image sends, list enrichment (name /
avatar / last message / unread), read receipts, and the unread
projection shape. Also locks in the no-N+1 guarantee on the list query.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.django_db]


def _start(client, recipient):
    return client.post(
        "/messaging/conversations/start/",
        {"recipient_id": str(recipient.id)},
        format="json",
    )


# ── Shared-workspace gating ─────────────────────────────────────────


def test_start_succeeds_between_workspace_members(client_for, alice, bob, shared_workspace):
    resp = _start(client_for(alice), bob)
    assert resp.status_code == 201
    assert resp.data["id"]
    # Enrichment fields are present (null/0) on the start response.
    assert resp.data["unread_count"] == 0


def test_start_is_idempotent(client_for, alice, bob, shared_workspace):
    first = _start(client_for(alice), bob)
    second = _start(client_for(alice), bob)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.data["id"] == second.data["id"]


def test_start_forbidden_without_shared_workspace(client_for, alice, carol, shared_workspace):
    resp = _start(client_for(alice), carol)
    assert resp.status_code == 403


def test_cannot_message_self(client_for, alice, shared_workspace):
    resp = _start(client_for(alice), alice)
    assert resp.status_code == 400


# ── Sending messages ────────────────────────────────────────────────


def test_send_text_message(client_for, alice, bob, shared_workspace):
    cid = _start(client_for(alice), bob).data["id"]
    resp = client_for(alice).post(
        f"/messaging/conversations/{cid}/messages/send/",
        {"body": "hey bob"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["body"] == "hey bob"
    assert resp.data["message_type"] == "text"
    assert resp.data["image"] is None


def test_send_image_message_returns_resolvable_url(client_for, alice, bob, shared_workspace, png_upload):
    cid = _start(client_for(alice), bob).data["id"]
    resp = client_for(alice).post(
        f"/messaging/conversations/{cid}/messages/send/",
        {"body": "", "image": png_upload},
        format="multipart",
    )
    assert resp.status_code == 201
    assert resp.data["message_type"] == "image"
    image = resp.data["image"]
    # A resolvable URL, NOT the bare storage key ("uploads/...").
    assert image
    assert image.startswith(("http://", "https://", "/"))
    assert "message_photos" in image


def test_send_rejects_empty_message(client_for, alice, bob, shared_workspace):
    cid = _start(client_for(alice), bob).data["id"]
    resp = client_for(alice).post(
        f"/messaging/conversations/{cid}/messages/send/",
        {"body": "   "},
        format="json",
    )
    assert resp.status_code == 400


def test_non_participant_cannot_send(client_for, alice, bob, carol, shared_workspace, add_member):
    add_member(carol)  # Carol now shares the workspace but is not in this thread.
    cid = _start(client_for(alice), bob).data["id"]
    resp = client_for(carol).post(
        f"/messaging/conversations/{cid}/messages/send/",
        {"body": "sneaky"},
        format="json",
    )
    assert resp.status_code == 404


# ── List enrichment ─────────────────────────────────────────────────


def test_conversation_list_is_enriched(client_for, alice, bob, shared_workspace):
    cid = _start(client_for(alice), bob).data["id"]
    # Bob replies, creating an unread for Alice.
    client_for(bob).post(
        f"/messaging/conversations/{cid}/messages/send/",
        {"body": "hello alice"},
        format="json",
    )

    resp = client_for(alice).get("/messaging/conversations/")
    assert resp.status_code == 200
    item = next(c for c in resp.data if c["id"] == cid)

    assert item["other_participant"]["user_id"] == str(bob.id)
    assert item["other_participant"]["display_name"]  # non-empty
    assert item["last_message"]["body"] == "hello alice"
    assert item["last_message"]["sender_id"] == str(bob.id)
    assert item["unread_count"] == 1


# ── Read receipts + unread projection ───────────────────────────────


def test_mark_read_zeroes_unread(client_for, alice, bob, shared_workspace):
    cid = _start(client_for(alice), bob).data["id"]
    client_for(bob).post(
        f"/messaging/conversations/{cid}/messages/send/",
        {"body": "ping"},
        format="json",
    )

    before = client_for(alice).get("/messaging/unread/")
    assert before.data["total"] == 1

    client_for(alice).post(f"/messaging/conversations/{cid}/read/")

    after = client_for(alice).get("/messaging/unread/")
    assert after.data["total"] == 0
    assert after.data["conversations"] == []


def test_unread_response_shape(client_for, alice, bob, shared_workspace):
    resp = client_for(alice).get("/messaging/unread/")
    assert resp.status_code == 200
    assert set(resp.data.keys()) == {"total", "conversations"}
    assert isinstance(resp.data["conversations"], list)


# ── No N+1 on the list query ────────────────────────────────────────


def test_list_query_count_is_bounded(
    client_for, alice, bob, carol, user_factory, shared_workspace, add_member, django_assert_max_num_queries
):
    """The list query count must not grow with the number of conversations."""
    from components.messaging.infrastructure.repositories.orm_conversation_repository import (
        OrmConversationRepository,
    )

    # Three conversations, each with a message.
    partners = [bob, add_member(carol), add_member(user_factory(username="dave", email="dave@example.com"))]
    for partner in partners:
        cid = _start(client_for(alice), partner).data["id"]
        client_for(partner).post(
            f"/messaging/conversations/{cid}/messages/send/",
            {"body": f"hi from {partner.username}"},
            format="json",
        )

    repo = OrmConversationRepository()
    with django_assert_max_num_queries(10):
        items = repo.list_for_user(alice.id)
    assert len(items) == 3
