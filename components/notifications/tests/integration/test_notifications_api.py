import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from infrastructure.persistence.notifications.models import (
    AINotificationPreference,
    Notification,
    WorkspaceNotificationPreference,
)
from components.notifications.infrastructure.adapters.notification_service import NotificationDispatcher
from components.notifications.infrastructure.adapters.utils import create_notification
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceCategory, SubCategory
from infrastructure.persistence.workspaces.news.models import News, Category as NewsCategory
from infrastructure.persistence.notifications.userpreferences.models import UserPreference


def _create_workspace(owner, suffix='workspace'):
    category = WorkspaceCategory.objects.create(name=f'Category {suffix}')
    subcategory = SubCategory.objects.create(name=f'Subcategory {suffix}', category=category)
    workspace = Workspace.objects.create(workspace_name=f'Workspace {suffix}', workspace_owner=owner, status='active')
    workspace.workspace_subcategories.add(subcategory)
    return workspace


@pytest.mark.django_db
def test_notification_list_returns_only_current_user(django_user_model):
    client = APIClient()
    recipient = django_user_model.objects.create_user(email='user@example.com', username='user', password='pass')
    actor = django_user_model.objects.create_user(email='actor@example.com', username='actor', password='pass')
    other_user = django_user_model.objects.create_user(email='other@example.com', username='other', password='pass')

    Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb='sent you a message',
        notification_type=Notification.NotificationType.MESSAGE,
    )
    Notification.objects.create(
        recipient=other_user,
        actor=actor,
        verb='pinged you',
        notification_type=Notification.NotificationType.SYSTEM,
    )

    client.force_authenticate(user=recipient)
    url = reverse('notifications:notification-list')
    response = client.get(url)

    assert response.status_code == 200
    assert len(response.data['results']) == 1
    assert response.data['results'][0]['notification_type'] == Notification.NotificationType.MESSAGE


@pytest.mark.django_db
def test_notification_list_filters_by_seed(django_user_model):
    client = APIClient()
    owner = django_user_model.objects.create_user(email='owner@example.com', username='owner', password='pass')
    recipient = django_user_model.objects.create_user(email='seeduser@example.com', username='seeduser', password='pass')
    actor = django_user_model.objects.create_user(email='actor4@example.com', username='actor4', password='pass')

    workspace_a = _create_workspace(owner, 'A')
    workspace_b = _create_workspace(owner, 'B')

    Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb='liked your workspace post',
        notification_type=Notification.NotificationType.LIKE,
        workspace=workspace_a,
    )
    Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb='liked something else',
        notification_type=Notification.NotificationType.LIKE,
        workspace=workspace_b,
    )

    client.force_authenticate(user=recipient)
    url = reverse('notifications:notification-list')
    response = client.get(f'{url}?workspace={workspace_a.id}')

    assert response.status_code == 200
    assert len(response.data['results']) == 1
    assert response.data['results'][0]['workspace']['id'] == str(workspace_a.id)


@pytest.mark.django_db
def test_mark_all_read_marks_notifications(django_user_model):
    client = APIClient()
    recipient = django_user_model.objects.create_user(email='recipient@example.com', username='recipient', password='pass')
    actor = django_user_model.objects.create_user(email='actor2@example.com', username='actor2', password='pass')

    Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb='liked your post',
        notification_type=Notification.NotificationType.LIKE,
    )
    Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb='commented on your post',
        notification_type=Notification.NotificationType.COMMENT,
    )

    client.force_authenticate(user=recipient)
    url = reverse('notifications:notification-mark-all-read')
    response = client.post(url)

    assert response.status_code == 200
    assert response.data['updated'] == 2
    assert Notification.objects.filter(recipient=recipient, is_read=True).count() == 2


@pytest.mark.django_db
def test_mark_all_read_scopes_by_seed(django_user_model):
    client = APIClient()
    owner = django_user_model.objects.create_user(email='seedowner@example.com', username='seedowner', password='pass')
    recipient = django_user_model.objects.create_user(email='seedrecipient@example.com', username='seedrecipient', password='pass')
    actor = django_user_model.objects.create_user(email='actor-workspace@example.com', username='actorseed', password='pass')

    workspace_a = _create_workspace(owner, 'markA')
    workspace_b = _create_workspace(owner, 'markB')

    Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb='update a',
        notification_type=Notification.NotificationType.SYSTEM,
        workspace=workspace_a,
    )
    Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb='update b',
        notification_type=Notification.NotificationType.SYSTEM,
        workspace=workspace_b,
    )

    client.force_authenticate(user=recipient)
    url = reverse('notifications:notification-mark-all-read')
    response = client.post(f'{url}?workspace={workspace_a.id}')

    assert response.status_code == 200
    assert response.data['updated'] == 1
    assert Notification.objects.filter(workspace=workspace_a, is_read=True).count() == 1
    assert Notification.objects.filter(workspace=workspace_b, is_read=False).count() == 1


@pytest.mark.django_db
def test_create_notification_helper_deduplicates(django_user_model):
    recipient = django_user_model.objects.create_user(email='dup@example.com', username='dup', password='pass')
    actor = django_user_model.objects.create_user(email='actor3@example.com', username='actor3', password='pass')

    first = create_notification(
        recipient=recipient,
        actor=actor,
        verb='liked your post',
        notification_type=Notification.NotificationType.LIKE,
    )
    duplicate = create_notification(
        recipient=recipient,
        actor=actor,
        verb='liked your post',
        notification_type=Notification.NotificationType.LIKE,
    )

    assert first.pk == duplicate.pk
    assert Notification.objects.count() == 1


@pytest.mark.django_db
def test_create_notification_helper_respects_workspace_scope(django_user_model):
    recipient = django_user_model.objects.create_user(email='seeddup@example.com', username='seeddup', password='pass')
    actor = django_user_model.objects.create_user(email='actor5@example.com', username='actor5', password='pass')
    owner = django_user_model.objects.create_user(email='owner2@example.com', username='owner2', password='pass')

    workspace_a = _create_workspace(owner, 'scopeA')
    workspace_b = _create_workspace(owner, 'scopeB')

    first = create_notification(
        recipient=recipient,
        actor=actor,
        verb='mention',
        notification_type=Notification.NotificationType.MENTION,
        workspace=workspace_a,
    )
    # Same actors but different workspace should create a new row
    second = create_notification(
        recipient=recipient,
        actor=actor,
        verb='mention',
        notification_type=Notification.NotificationType.MENTION,
        workspace=workspace_b,
    )
    # Same workspace should deduplicate
    third = create_notification(
        recipient=recipient,
        actor=actor,
        verb='mention',
        notification_type=Notification.NotificationType.MENTION,
        workspace=workspace_a,
    )

    assert first.pk != second.pk
    assert first.pk == third.pk


def _create_news(workspace, author, slug_suffix='news'):
    category = NewsCategory.objects.create(name=f'Category-{slug_suffix}')
    return News.objects.create(
        workspace=workspace,
        image='image.png',
        title=f'Title {slug_suffix}',
        excerpt='Excerpt {slug_suffix}',
        body='Body {slug_suffix}',
        author=author,
        slug=f'{slug_suffix}-slug',
        category=category,
    )


@pytest.mark.django_db
def test_news_creation_emits_notifications_for_followers(django_user_model):
    owner = django_user_model.objects.create_user(email='owner@example.com', username='owner', password='pass')
    follower = django_user_model.objects.create_user(email='follower@example.com', username='follower', password='pass')

    workspace = _create_workspace(owner, 'news')
    workspace.followers.add(follower)

    _create_news(workspace, owner, 'general')

    notification = Notification.objects.filter(recipient=follower).first()
    assert notification is not None
    assert 'published news' in notification.verb


@pytest.mark.django_db
def test_notifications_respect_user_preference_toggle(django_user_model):
    owner = django_user_model.objects.create_user(email='pref-owner@example.com', username='prefowner', password='pass')
    follower = django_user_model.objects.create_user(email='pref-follower@example.com', username='preffollower', password='pass')
    UserPreference.objects.create(user=follower, notifications_enabled=False)

    workspace = _create_workspace(owner, 'pref-workspace')
    workspace.followers.add(follower)

    _create_news(workspace, owner, 'pref-news')

    assert not Notification.objects.filter(recipient=follower).exists()


@pytest.mark.django_db
def test_workspace_notification_preference_blocks_workspace_specific_notifications(django_user_model):
    owner = django_user_model.objects.create_user(email='seedpref@example.com', username='seedpref', password='pass')
    follower = django_user_model.objects.create_user(email='seedpref-follower@example.com', username='seedpreffollower', password='pass')

    workspace = _create_workspace(owner, 'workspace-pref')
    workspace.followers.add(follower)
    WorkspaceNotificationPreference.objects.create(user=follower, workspace=workspace, is_enabled=False)

    _create_news(workspace, owner, 'seedpref-news')

    assert not Notification.objects.filter(recipient=follower).exists()


@pytest.mark.django_db
def test_workspace_notification_preference_api_allows_toggle(django_user_model):
    client = APIClient()
    user = django_user_model.objects.create_user(email='toggle@example.com', username='toggle', password='pass')
    owner = django_user_model.objects.create_user(email='toggle-owner@example.com', username='toggle-owner', password='pass')
    workspace = _create_workspace(owner, 'toggle')

    client.force_authenticate(user=user)
    url = reverse('notifications:workspace-notification-preference-list')
    response = client.post(url, {'workspace': str(workspace.id), 'is_enabled': False}, format='json')

    assert response.status_code == 201
    assert WorkspaceNotificationPreference.objects.filter(user=user, workspace=workspace, is_enabled=False).exists()

    list_response = client.get(url)
    assert list_response.status_code == 200
    assert list_response.data['results'][0]['workspace'] == str(workspace.id)
    assert Notification.objects.count() == 2


@pytest.mark.django_db
def test_workspace_notification_preference_detail_uses_workspace_id(django_user_model):
    client = APIClient()
    user = django_user_model.objects.create_user(email='workspace-detail@example.com', username='workspace-detail', password='pass')
    owner = django_user_model.objects.create_user(email='workspace-detail-owner@example.com', username='workspace-detail-owner', password='pass')
    workspace = _create_workspace(owner, 'workspace-detail')
    preference = WorkspaceNotificationPreference.objects.create(user=user, workspace=workspace, is_enabled=True)

    client.force_authenticate(user=user)
    url = reverse('notifications:workspace-notification-preference-detail', args=[str(workspace.id)])
    response = client.patch(url, {'is_enabled': False}, format='json')

    assert response.status_code == 200
    preference.refresh_from_db()
    assert preference.is_enabled is False


@pytest.mark.django_db
def test_ai_notification_preference_api_is_scoped(django_user_model):
    client = APIClient()
    user = django_user_model.objects.create_user(email='ai@example.com', username='ai', password='pass')
    other = django_user_model.objects.create_user(email='other-ai@example.com', username='other-ai', password='pass')
    owner = django_user_model.objects.create_user(email='workspace-owner@example.com', username='workspace-owner', password='pass')
    workspace = _create_workspace(owner, 'ai')

    client.force_authenticate(user=user)
    url = reverse('notifications:ai-notification-preference-list')
    response = client.post(
        url,
        {'workspace': str(workspace.id), 'channel': AINotificationPreference.CHANNEL_ACTION_CREATED, 'is_enabled': False},
        format='json',
    )
    assert response.status_code == 201
    assert AINotificationPreference.objects.filter(user=user, workspace=workspace).count() == 1

    AINotificationPreference.objects.create(
        user=other,
        workspace=workspace,
        channel=AINotificationPreference.CHANNEL_ACTION_CREATED,
        is_enabled=False,
    )

    list_response = client.get(url)
    assert list_response.status_code == 200
    assert len(list_response.data['results']) == 1
    assert list_response.data['results'][0]['channel'] == AINotificationPreference.CHANNEL_ACTION_CREATED


@pytest.mark.django_db
def test_ai_notification_preference_detail_uses_workspace_id(django_user_model):
    client = APIClient()
    user = django_user_model.objects.create_user(email='ai-detail@example.com', username='ai-detail', password='pass')
    owner = django_user_model.objects.create_user(email='ai-detail-owner@example.com', username='ai-detail-owner', password='pass')
    workspace = _create_workspace(owner, 'ai-detail')
    preference = AINotificationPreference.objects.create(
        user=user,
        workspace=workspace,
        channel=AINotificationPreference.CHANNEL_ACTION_ERROR,
        is_enabled=False,
    )

    client.force_authenticate(user=user)
    url = reverse('notifications:ai-notification-preference-detail', args=[str(workspace.id)])
    response = client.patch(url, {'is_enabled': True}, format='json')

    assert response.status_code == 200
    preference.refresh_from_db()
    assert preference.is_enabled is True


@pytest.mark.django_db
def test_ai_channel_preference_blocks_notifications(django_user_model):
    dispatcher = NotificationDispatcher()
    owner = django_user_model.objects.create_user(email='pref-owner@example.com', username='prefowner2', password='pass')
    actor = django_user_model.objects.create_user(email='ai-actor@example.com', username='aiactor', password='pass')
    follower = django_user_model.objects.create_user(email='pref-follower2@example.com', username='follower2', password='pass')
    workspace = _create_workspace(owner, 'ai-pref')
    workspace.followers.add(follower)
    AINotificationPreference.objects.create(
        user=follower,
        workspace=workspace,
        channel=AINotificationPreference.CHANNEL_ACTION_CREATED,
        is_enabled=False,
    )

    dispatcher.dispatch(
        actor=actor,
        workspace=workspace,
        verb='Orchestrator created an action',
        notification_type=Notification.NotificationType.AI_EVENT,
        recipients=[follower],
        metadata={},
        target=workspace,
        ai_channel=AINotificationPreference.CHANNEL_ACTION_CREATED,
    )

    assert not Notification.objects.filter(recipient=follower).exists()


@pytest.mark.django_db
def test_notification_list_period_filter(django_user_model):
    client = APIClient()
    recipient = django_user_model.objects.create_user(email='period@example.com', username='period', password='pass')
    actor = django_user_model.objects.create_user(email='actor-period@example.com', username='actor-period', password='pass')

    recent = Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb='recent',
        notification_type=Notification.NotificationType.SYSTEM,
    )
    old = Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb='old',
        notification_type=Notification.NotificationType.SYSTEM,
    )
    Notification.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=10))

    client.force_authenticate(user=recipient)
    url = reverse('notifications:notification-list')
    response = client.get(f'{url}?period=last_7_days')

    assert response.status_code == 200
    assert len(response.data['results']) == 1
    assert response.data['results'][0]['verb'] == 'recent'


@pytest.mark.django_db
def test_notification_logo_url_included(django_user_model):
    client = APIClient()
    recipient = django_user_model.objects.create_user(email='logo@example.com', username='logo', password='pass')
    actor = django_user_model.objects.create_user(email='actor-logo@example.com', username='actor-logo', password='pass')

    Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb='with logo',
        notification_type=Notification.NotificationType.SYSTEM,
        logo_url='https://cdn.example.com/logo.png',
    )

    client.force_authenticate(user=recipient)
    url = reverse('notifications:notification-list')
    response = client.get(url)

    assert response.status_code == 200
    assert response.data['results'][0]['logo_url'] == 'https://cdn.example.com/logo.png'
