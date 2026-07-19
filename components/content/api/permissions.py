"""Content bounded context DRF permissions.

Three named permission classes wrap the canonical
``has_workspace_permission`` factory so controllers read like plain
English:

- ``CanReadWriting`` — workspace-scoped read of drafts / newsletters /
  blogs / templates / subscribers. Anyone with workspace access (owner,
  admin, contributor-equivalent roles) gets this; viewer-only seats do
  NOT.
- ``CanComposeWriting`` — create / update / delete drafts, edit
  templates, manage subscribers. Bound to roles that author copy
  (owner, admin, campaign_manager, donation_steward).
- ``CanSendNewsletter`` — send + schedule + test-send + regenerate.
  Narrowly held by owner + admin only because email send is a one-way
  action.

The legacy ``IsOwnerOrReadOnly`` is kept for back-compat with the older
News-blog controller (``components/content/api/controller.py``) until
that surface migrates to ``CanComposeWriting``. New code MUST use the
new classes — adding ``IsOwnerOrReadOnly`` to new endpoints is a
regression.

Permission-key bindings to system roles live in
``infrastructure/persistence/workspaces/migrations/0030_seed_writing_permissions.py``.
The keys themselves are registered in
``components/membership/api/groups_controller.VALID_PERMISSION_KEYS``.
"""

from __future__ import annotations

from rest_framework import permissions

from components.membership.api.permissions import has_workspace_permission


# New, RBAC-backed classes — preferred for all writing-surface controllers.
CanReadWriting = has_workspace_permission("view_writing")
CanComposeWriting = has_workspace_permission("manage_writing")
CanSendNewsletter = has_workspace_permission("manage_newsletter_send")
# Subscribers + templates ride the same gate as composing — both are
# author-side concerns. Aliasing keeps the controller permission_classes
# readable even though they resolve to the same key.
CanManageSubscribers = CanComposeWriting
CanManageTemplates = CanComposeWriting


class IsOwnerOrReadOnly(permissions.BasePermission):
    """Legacy. Allow read access to anyone, write access only to the object owner.

    Retained for the News-blog controller pending its migration to the
    RBAC-backed classes above. Do NOT use on new endpoints — it doesn't
    enforce workspace membership and treats ``request.user == obj.owner``
    as sufficient authorization for writes.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        # The News blog model identifies its owner via ``author``; older
        # models use ``owner``. Treat either attribute as the owning user
        # so writes on a resolved object actually authorize the creator.
        owner = getattr(obj, "owner", None) or getattr(obj, "author", None)
        return owner == request.user
