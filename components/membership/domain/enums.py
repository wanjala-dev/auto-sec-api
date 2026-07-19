"""Domain enums for the membership bounded context.

Canonical definitions for workspace and team membership roles and statuses.
"""

from __future__ import annotations


class WorkspaceMembershipRole:
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    _ALL = {OWNER, ADMIN, MEMBER, VIEWER}


class WorkspaceMembershipStatus:
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    _ALL = {INVITED, ACTIVE, SUSPENDED}
