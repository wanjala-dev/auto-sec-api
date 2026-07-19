import pytest
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.urls import reverse
from django.utils.encoding import smart_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient

from infrastructure.persistence.notifications.models import Notification
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import Workspace


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def system_actor():
    return CustomUser.objects.create_superuser(
        email="admin@example.com",
        username="admin",
        password="adminpass123",
    )


@pytest.fixture(autouse=True)
def disable_security_events_async(settings):
    settings.SECURITY_EVENTS_ASYNC = False


def create_user(email: str = "user@example.com", username: str = "user") -> CustomUser:
    user = CustomUser.objects.create_user(
        email=email,
        username=username,
        password="password123",
    )
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return user


@pytest.mark.django_db
def test_login_creates_notification(api_client, system_actor, django_capture_on_commit_callbacks):
    user = create_user()
    # Security notifications flow through the dispatcher funnel (post-commit
    # enqueue) — flush on_commit callbacks so eager Celery runs.
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(
            reverse("login"),
            {"email": user.email, "password": "password123"},
            format="json",
        )
    assert response.status_code == 200
    assert Notification.objects.filter(
        recipient=user,
        metadata__event="auth.login",
    ).exists()


@pytest.mark.django_db
def test_logout_creates_notification(api_client, system_actor, django_capture_on_commit_callbacks):
    user = create_user(email="logout@example.com", username="logout-user")
    login_response = api_client.post(
        reverse("login"),
        {"email": user.email, "password": "password123"},
        format="json",
    )
    refresh_token = login_response.data["tokens"]["refresh"]
    api_client.force_authenticate(user=user)
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(
            reverse("logout"),
            {"refresh": refresh_token},
            format="json",
        )
    assert response.status_code == 204
    assert Notification.objects.filter(
        recipient=user,
        metadata__event="auth.logout",
    ).exists()


@pytest.mark.django_db
def test_password_reset_notifications(api_client, system_actor, django_capture_on_commit_callbacks):
    user = create_user(email="reset@example.com", username="reset-user")
    with django_capture_on_commit_callbacks(execute=True):
        request_response = api_client.post(
            reverse("request-reset-email"),
            {"email": user.email},
            format="json",
        )
    assert request_response.status_code == 200
    assert Notification.objects.filter(
        recipient=user,
        metadata__event="auth.password_reset_requested",
    ).exists()

    token = PasswordResetTokenGenerator().make_token(user)
    uidb64 = urlsafe_base64_encode(smart_bytes(user.id))
    with django_capture_on_commit_callbacks(execute=True):
        complete_response = api_client.patch(
            reverse("password-reset-complete"),
            {
                "password": "newpassword321",
                "token": token,
                "uidb64": uidb64,
            },
            format="json",
        )
    assert complete_response.status_code == 200
    assert Notification.objects.filter(
        recipient=user,
        metadata__event="auth.password_reset_completed",
    ).exists()


@pytest.mark.django_db
def test_login_returns_org_onboarding_flags_for_new_user(api_client, system_actor):
    user = create_user(email="onboard@example.com", username="onboard-user")
    response = api_client.post(
        reverse("login"),
        {"email": user.email, "password": "password123"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["requires_org_onboarding"] is True
    assert response.data["org_membership_count"] == 0
    assert response.data["org_access_workspaces"] == []


@pytest.mark.django_db
def test_login_returns_org_onboarding_flags_for_workspace_owner(api_client, system_actor):
    user = create_user(email="owner@example.com", username="owner-user")
    # status='active' makes this a real owned org. The Workspace model defaults
    # status to 'inactive' (= archived), and the user-context accessible/count
    # query uses the active-only default manager — an owner of only an archived
    # org correctly counts as 0 orgs. Without status='active' this asserts the
    # old all_objects() behaviour that leaked archived orgs into the count.
    Workspace.objects.create(workspace_name="Owner Workspace", workspace_owner=user, status="active")
    response = api_client.post(
        reverse("login"),
        {"email": user.email, "password": "password123"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["requires_org_onboarding"] is False
    assert response.data["org_membership_count"] == 1
    assert len(response.data["org_access_workspaces"]) == 1
