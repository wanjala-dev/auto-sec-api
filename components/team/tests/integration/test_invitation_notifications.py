import pytest
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from infrastructure.persistence.notifications.models import Notification
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.team.models import Invitation, Team
from infrastructure.persistence.users.models import CustomUser, UserProfile


def _create_user(email: str, username: str) -> CustomUser:
    user = CustomUser.objects.create_user(
        email=email,
        username=username,
        password='pass1234',
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def _create_seed(owner: CustomUser) -> Workspace:
    return Workspace.objects.create(
        workspace_name='Test Workspace',
        workspace_owner=owner,
        status='active',
    )



@pytest.mark.django_db
def test_invitation_emits_notification_for_invited_user(
    django_capture_on_commit_callbacks,
):
    owner = _create_user('owner@example.com', 'owner')
    invited = _create_user('invited@example.com', 'invited')
    workspace = _create_seed(owner)
    team = Team.objects.create(workspace=workspace, title='Alpha', created_by=owner)
    team.members.add(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    # The notification dispatch is deferred to transaction commit
    # (NotificationDispatcher.dispatch → db_transaction.on_commit →
    # dispatch_notification_async). Capture + run those callbacks so the
    # async path is exercised; with CELERY_TASK_ALWAYS_EAGER the task then
    # creates the Notification synchronously.
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse('membership:membership-invite'),
            {
                'user': owner.id,
                'email': invited.email,
                'workspace': str(workspace.id),
                'team': team.id,
            },
            format='json',
        )

    assert response.status_code == 200
    assert Notification.objects.filter(
        recipient=invited,
        verb__icontains='invited you to join team',
    ).exists()


@pytest.mark.django_db
def test_invitation_sets_contributor_and_active_org():
    owner = _create_user('owner-active@example.com', 'owner-active')
    invited = _create_user('invited-active@example.com', 'invited-active')
    workspace = _create_seed(owner)
    team = Team.objects.create(workspace=workspace, title='Gamma', created_by=owner)
    team.members.add(owner)

    invited_profile = invited.profile
    invited_profile.active_workspace_id = None
    invited_profile.active_team_id = 0
    invited_profile.save(update_fields=['active_workspace_id', 'active_team_id'])

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse('membership:membership-invite'),
        {
            'user': owner.id,
            'email': invited.email,
            'workspace': str(workspace.id),
            'team': team.id,
        },
        format='json',
    )

    assert response.status_code == 200

    invited.refresh_from_db()
    invited.profile.refresh_from_db()

    assert invited.is_contributor is True
    assert invited.profile.active_workspace_id == workspace.id
    assert invited.profile.active_team_id == team.id
    assert team.members.filter(id=invited.id).exists()


@pytest.mark.django_db
def test_invitation_creates_new_user_with_contributor_membership():
    owner = _create_user('owner-new@example.com', 'owner-new')
    workspace = _create_seed(owner)
    team = Team.objects.create(workspace=workspace, title='Delta', created_by=owner)
    team.members.add(owner)

    invite_email = 'brandnew@example.com'
    assert not CustomUser.objects.filter(email=invite_email).exists()

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse('membership:membership-invite'),
        {
            'user': owner.id,
            'email': invite_email,
            'workspace': str(workspace.id),
            'team': team.id,
        },
        format='json',
    )

    assert response.status_code == 200

    invited = CustomUser.objects.get(email=invite_email)
    invited.profile.refresh_from_db()

    assert invited.is_contributor is True
    assert invited.profile.active_workspace_id == workspace.id
    assert invited.profile.active_team_id == team.id
    assert team.members.filter(id=invited.id).exists()

@pytest.mark.django_db
def test_invitation_email_includes_password_setup_link_for_new_user():
    owner = _create_user('owner-email@example.com', 'owner-email')
    workspace = _create_seed(owner)
    team = Team.objects.create(workspace=workspace, title='Email', created_by=owner)
    team.members.add(owner)

    invite_email = 'firsttime@example.com'

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse('membership:membership-invite'),
        {
            'user': owner.id,
            'email': invite_email,
            'workspace': str(workspace.id),
            'team': team.id,
        },
        format='json',
    )

    assert response.status_code == 200

    invite_messages = [msg for msg in mail.outbox if 'invited you to join' in msg.subject]
    assert invite_messages
    invite_msg = invite_messages[-1]
    html_body = invite_msg.alternatives[0][0] if invite_msg.alternatives else invite_msg.body
    assert '/PasswordResetConfirm/' in html_body


@pytest.mark.django_db
def test_invitation_without_team_uses_contributors_team():
    owner = _create_user('owner-contrib@example.com', 'owner-contrib')
    workspace = _create_seed(owner)

    invite_email = 'default-team@example.com'

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse('membership:membership-invite'),
        {
            'user': owner.id,
            'email': invite_email,
            'workspace': str(workspace.id),
        },
        format='json',
    )

    assert response.status_code == 200

    default_team = Team.objects.filter(workspace=workspace, is_default=True).first()
    assert default_team is not None

    invitation = Invitation.objects.get(email=invite_email, workspace=workspace)
    assert invitation.team_id == default_team.id

    invited = CustomUser.objects.get(email=invite_email)
    invited.profile.refresh_from_db()

    assert invited.profile.active_team_id == default_team.id
    assert invited.profile.active_workspace_id == workspace.id
    assert default_team.members.filter(id=invited.id).exists()


@pytest.mark.django_db
def test_accepting_invitation_notifies_team_members(
    django_capture_on_commit_callbacks,
):
    owner = _create_user('owner2@example.com', 'owner2')
    invited = _create_user('invited2@example.com', 'invited2')
    workspace = _create_seed(owner)
    team = Team.objects.create(workspace=workspace, title='Beta', created_by=owner)
    team.members.add(owner)

    invitation = Invitation.objects.create(
        workspace=workspace,
        team=team,
        email=invited.email,
        code='CODE',
    )

    client = APIClient()
    client.force_authenticate(user=invited)
    # Accept-notification dispatch is deferred to commit too — capture +
    # run the on_commit callbacks so the team-member notification lands.
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse('membership:membership-accept-invitation'),
            {
                'code': invitation.code,
                'email': invited.email,
                'user': invited.id,
            },
            format='json',
        )

    assert response.status_code == 200
    invitation.refresh_from_db()
    assert invitation.accepted_at is not None
    assert Notification.objects.filter(
        recipient=owner,
        verb__icontains='joined team',
    ).exists()


@pytest.mark.django_db
def test_team_members_endpoint_includes_joined_at_for_members():
    owner = _create_user('owner-members@example.com', 'owner-members')
    invited = _create_user('invited-members@example.com', 'invited-members')
    workspace = _create_seed(owner)
    team = Team.objects.create(workspace=workspace, title='Joined', created_by=owner)
    team.members.add(owner)

    invitation = Invitation.objects.create(
        workspace=workspace,
        team=team,
        email=invited.email,
        code='JOINED',
    )

    client = APIClient()
    client.force_authenticate(user=invited)
    accept_response = client.post(
        reverse('membership:membership-accept-invitation'),
        {
            'code': invitation.code,
            'email': invited.email,
            'user': invited.id,
        },
        format='json',
    )
    assert accept_response.status_code == 200

    client.force_authenticate(user=owner)
    response = client.get(
        reverse('membership:membership-members'),
        {'workspace_id': str(workspace.id)},
        format='json',
    )
    assert response.status_code == 200

    results = response.data['results']
    invited_entry = next(item for item in results if item['email'] == invited.email)
    team_payload = next(team_info for team_info in invited_entry['teams'] if team_info['id'] == team.id)
    assert team_payload['joined_at'] is not None


@pytest.mark.django_db
def test_pending_invitations_endpoint_groups_by_email():
    owner = _create_user('owner-pending@example.com', 'owner-pending')
    workspace = _create_seed(owner)
    team_a = Team.objects.create(workspace=workspace, title='Alpha', created_by=owner)
    team_b = Team.objects.create(workspace=workspace, title='Beta', created_by=owner)
    team_a.members.add(owner)
    team_b.members.add(owner)

    Invitation.objects.create(
        workspace=workspace,
        team=team_a,
        email='pending@example.com',
        code='PEND1',
    )
    Invitation.objects.create(
        workspace=workspace,
        team=team_b,
        email='pending@example.com',
        code='PEND2',
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.get(
        reverse('membership:membership-pending-invitations'),
        {'workspace_id': str(workspace.id)},
        format='json',
    )

    assert response.status_code == 200
    assert response.data['count'] == 1
    pending_entry = response.data['results'][0]
    assert pending_entry['email'] == 'pending@example.com'
    assert {team['team_title'] for team in pending_entry['teams']} == {'Alpha', 'Beta'}
