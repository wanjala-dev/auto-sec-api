from django import template
from django.db.models import Q
from infrastructure.persistence.notifications.models import Notification

register = template.Library()

@register.inclusion_tag('social/show_notifications.html', takes_context=True)
def show_notifications(context):
	request_user = context['request'].user
	if not request_user.is_authenticated:
		return {'notifications': Notification.objects.none()}
	profile = getattr(request_user, 'profile', None)
	active_workspace_id = getattr(profile, 'active_workspace_id', None)
	notifications = Notification.objects.filter(recipient=request_user, is_read=False)
	if active_workspace_id:
		notifications = notifications.filter(Q(workspace_id=active_workspace_id) | Q(workspace__isnull=True))
	notifications = notifications.order_by('-created_at')
	return {'notifications': notifications}
