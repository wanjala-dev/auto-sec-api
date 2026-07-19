"""Canonical domain enums for the team bounded context.

Team-specific enums extracted from the workspace domain.
"""

from __future__ import annotations


class TeamStatus:
    ACTIVE = "active"
    DELETED = "deleted"
    _ALL = {ACTIVE, DELETED}


class TeamKind:
    DEPARTMENT = "department"
    PROJECT_TEAM = "project_team"
    AI_AGENTS = "ai_agents"
    _ALL = {DEPARTMENT, PROJECT_TEAM, AI_AGENTS}


class TeamPrivacy:
    PUBLIC = "public"
    PRIVATE = "private"
    _ALL = {PUBLIC, PRIVATE}


class TeamMembershipRole:
    LEAD = "lead"
    EDITOR = "editor"
    VIEWER = "viewer"
    _ALL = {LEAD, EDITOR, VIEWER}


class TeamMembershipStatus:
    ACTIVE = "active"
    SUSPENDED = "suspended"
    _ALL = {ACTIVE, SUSPENDED}


class InvitationStatus:
    INVITED = "invited"
    ACCEPTED = "accepted"
    _ALL = {INVITED, ACCEPTED}


class PlanStatus:
    ACTIVE = "active"
    CANCELED = "canceled"
    _ALL = {ACTIVE, CANCELED}
