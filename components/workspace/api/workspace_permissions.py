from rest_framework import permissions
from django.contrib.auth import get_user_model

class IsLoggedInUserOrAdmin(permissions.BasePermission):
    
    def has_object_permission(self, request, view, obj):
        return obj == request.user or request.user.is_staff


class IsAdminUser(permissions.BasePermission):

    def has_permission(self, request, view):
        return request.user and request.user.is_staff

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_staff

class IsOwner(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user

         
ADMIN_USER_DETAIL_DATA_ACCESS = (
    'username',
    'email',
    'bio',
    'is_staff',
    'is_admin',
    'is_active',
    'date_joined',
    'user_type',
    'points',
    'profile_image_id',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count',
    'get_following_count',
    'get_followers_count',
    'get_blocking_count',
    'get_blocked_count',
    'get_reported_users_count',
    'get_reported_sceneries_count',
    'get_reported_requests_count',
    'get_reported_comments_count',
    'get_reports_count',
    'get_reported_by_count'
)
ADMIN_USER_DETAIL_READ_ONLY_DATA_ACCESS = (
    'id',
    'is_staff',
    'is_admin',
    'is_active',
    'date_joined',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count',
    'get_following_count',
    'get_followers_count',
    'get_blocking_count',
    'get_blocked_count',
    'get_reported_users_count',
    'get_reported_sceneries_count',
    'get_reported_requests_count',
    'get_reported_comments_count',
    'get_reports_count',
    'get_reported_by_count'
)
ADMIN_USER_DETAIL_DATA_ACCESS_FULL = (
    'id',
) + ADMIN_USER_DETAIL_DATA_ACCESS
ADMIN_USER_LIST_DATA_ACCESS_FULL = (
    'id',
    'username',
    'email',
    'bio',
    'is_staff',
    'is_admin',
    'is_active',
    'date_joined',
    'user_type',
    'points',
    'profile_image_id',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count',
    'get_following_count',
    'get_followers_count',
    'get_blocking_count',
    'get_blocked_count',
    'get_reported_users_count',
    'get_reported_sceneries_count',
    'get_reported_requests_count',
    'get_reported_comments_count',
    'get_reports_count',
    'get_reported_by_count'
)
ADMIN_USER_LIST_READ_ONLY_DATA_ACCESS = ADMIN_USER_LIST_DATA_ACCESS_FULL

STAFF_USER_DETAIL_DATA_ACCESS = (
    'username',
    'email',
    'bio',
    'is_staff',
    'is_admin',
    'is_active',
    'date_joined',
    'user_type',
    'points',
    'profile_image_id',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count',
    'get_following_count',
    'get_followers_count',
    'get_blocking_count',
    'get_blocked_count',
    'get_reported_users_count',
    'get_reported_sceneries_count',
    'get_reported_requests_count',
    'get_reported_comments_count',
    'get_reports_count',
    'get_reported_by_count'
)
STAFF_USER_DETAIL_READ_ONLY_DATA_ACCESS = (
    'id',
    'is_staff',
    'is_admin',
    'is_active',
    'date_joined',
    'points',
    'profile_image_id',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count',
    'get_following_count',
    'get_followers_count',
    'get_blocking_count',
    'get_blocked_count',
    'get_reported_users_count',
    'get_reported_sceneries_count',
    'get_reported_requests_count',
    'get_reported_comments_count',
    'get_reports_count',
    'get_reported_by_count'
)
STAFF_USER_DETAIL_DATA_ACCESS_FULL = (
    'id',
) + STAFF_USER_DETAIL_DATA_ACCESS
STAFF_USER_LIST_DATA_ACCESS_FULL = (
    'id',
    'username',
    'email',
    'bio',
    'is_staff',
    'is_admin',
    'is_active',
    'date_joined',
    'user_type',
    'points',
    'profile_image_id',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count',
    'get_following_count',
    'get_followers_count',
    'get_blocking_count',
    'get_blocked_count',
    'get_reported_users_count',
    'get_reported_sceneries_count',
    'get_reported_requests_count',
    'get_reported_comments_count',
    'get_reports_count',
    'get_reported_by_count'
)
STAFF_USER_LIST_READ_ONLY_DATA_ACCESS = STAFF_USER_LIST_DATA_ACCESS_FULL

AUTHENTICATED_SELF_USER_DETAIL_DATA_ACCESS = (
    'username',
    'email',
    'bio',
    'is_staff',
    'is_admin',
    'is_active',
    'date_joined',
    'user_type',
    'points',
    'profile_image_id',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count',
    'get_following_count',
    'get_followers_count',
    'get_blocking_count',
    'get_blocked_count',
    'get_reported_users_count',
    'get_reported_sceneries_count',
    'get_reported_requests_count',
    'get_reported_comments_count',
    'get_reports_count',
    'get_reported_by_count'
)
AUTHENTICATED_SELF_USER_DETAIL_READ_ONLY_DATA_ACCESS = (
    'id',
    'is_staff',
    'is_admin',
    'is_active',
    'date_joined',
    'user_type',
    'points',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count',
    'get_following_count',
    'get_followers_count',
    'get_blocking_count',
    'get_blocked_count',
    'get_reported_users_count',
    'get_reported_sceneries_count',
    'get_reported_requests_count',
    'get_reported_comments_count',
    'get_reports_count',
    'get_reported_by_count'
)
AUTHENTICATED_SELF_USER_DETAIL_DATA_ACCESS_FULL = (
    'id',
) + AUTHENTICATED_SELF_USER_DETAIL_DATA_ACCESS
AUTHENTICATED_USER_LIST_DATA_ACCESS_FULL = (
    'id',
    'username',
    'bio',
    'is_staff',
    'is_admin',
    'is_active',
    'user_type',
    'points',
    'profile_image_id',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count',
    'get_following_count',
    'get_followers_count'
)
AUTHENTICATED_USER_LIST_READ_ONLY_DATA_ACCESS = AUTHENTICATED_USER_LIST_DATA_ACCESS_FULL

AUTHENTICATED_OTHER_USER_DETAIL_DATA_ACCESS = (
    'username',
    'bio',
    'is_staff',
    'is_admin',
    'is_active',
    'date_joined',
    'user_type',
    'points',
    'profile_image_id',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count'
)
AUTHENTICATED_OTHER_USER_DETAIL_DATA_ACCESS_FULL = (
    'id',
) + AUTHENTICATED_OTHER_USER_DETAIL_DATA_ACCESS
AUTHENTICATED_OTHER_USER_DETAIL_READ_ONLY_DATA_ACCESS = AUTHENTICATED_OTHER_USER_DETAIL_DATA_ACCESS_FULL

UNAUTHENTICATED_USER_DETAIL_DATA_ACCESS = (
    'username',
    'bio',
    'points',
    'profile_image_id',
    'get_bronze_badge_count',
    'get_silver_badge_count',
    'get_gold_badge_count'
)
UNAUTHENTICATED_USER_DETAIL_DATA_ACCESS_FULL = (
    'id',
) + UNAUTHENTICATED_USER_DETAIL_DATA_ACCESS
UNAUTHENTICATED_USER_DETAIL_READ_ONLY_DATA_ACCESS = UNAUTHENTICATED_USER_DETAIL_DATA_ACCESS_FULL
UNAUTHENTICATED_USER_LIST_DATA_ACCESS_FULL = (
    'id',
    'username',
    'bio',
    'points',
    'profile_image_id'
)
UNAUTHENTICATED_USER_LIST_READ_ONLY_DATA_ACCESS = UNAUTHENTICATED_USER_LIST_DATA_ACCESS_FULL


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
        Custom permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner of the snippet.
        return obj.author == request.user

class IsOwnerOrAdminOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.author == request.user or getattr(request.user, 'is_superuser', False)

class IsOwnerOrAdminOrStaffOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if hasattr(obj, 'author'):
            return obj.author == request.user or getattr(request.user, 'is_superuser', False) or request.user.is_staff
        elif isinstance(obj, get_user_model()):
            return obj.id == request.user.id or getattr(request.user, 'is_superuser', False) or request.user.is_staff
        return False


class IsUnauthenticatedOrAdminOrStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated
