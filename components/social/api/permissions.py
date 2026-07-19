from rest_framework import permissions
from components.team.application.providers.team_models_provider import get_team_models_provider
Team = get_team_models_provider().Team

class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        else:
            return obj.author == request.user

class CanMessageUser(permissions.BasePermission):
    """
    Permission to ensure users can only message:
    1. Other users in the same workspace/organization
    2. Users who are members of the same team
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True

        # For creating messages/threads
        if request.method == 'POST':
            data = request.data

            # Get sender and receiver
            sender_id = data.get('sender_user') or data.get('user')
            receiver_id = data.get('receiver_user') or data.get('receiver')
            workspace_id = data.get('workspace')

            if not sender_id or not receiver_id:
                return False

            # Sender must be the current user
            if str(sender_id) != str(request.user.id):
                return False

            # Check if users are in the same workspace
            if workspace_id:
                # Both users must be members of the same workspace
                sender_teams = Team.objects.filter(
                    workspace_id=workspace_id,
                    members=request.user,
                    status='active'
                ).exists()
                receiver_teams = Team.objects.filter(
                    workspace_id=workspace_id,
                    members__id=receiver_id,
                    status='active'
                ).exists()

                if not (sender_teams and receiver_teams):
                    return False

            return True

        return True

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            # Users can only read messages they're part of
            if hasattr(obj, 'sender_user') and hasattr(obj, 'receiver_user'):
                return (obj.sender_user == request.user or
                       obj.receiver_user == request.user)
            elif hasattr(obj, 'user') and hasattr(obj, 'receiver'):
                return (obj.user == request.user or
                       obj.receiver == request.user)
            return True

        # Users can only modify their own messages/threads
        if hasattr(obj, 'sender_user'):
            return obj.sender_user == request.user
        elif hasattr(obj, 'user'):
            return obj.user == request.user

        return False
