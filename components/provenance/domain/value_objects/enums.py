"""Framework-free enums for the provenance/access graph domain.

These mirror the ``TextChoices`` on the ORM models
(``infrastructure/persistence/provenance/models.py``) but carry no Django
dependency — the domain layer stays importable without the framework.
"""

from __future__ import annotations

from enum import StrEnum


class ActorType(StrEnum):
    HUMAN = "human"
    SERVICE_ACCOUNT = "service_account"
    AI_AGENT = "ai_agent"
    VENDOR_INTEGRATION = "vendor_integration"


class PermissionLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"


class SourceSystem(StrEnum):
    INTERNAL = "internal"
    AI = "ai"
    IDENTITY = "identity"
    AWS = "aws"
    OKTA = "okta"
    GOOGLE_WORKSPACE = "google_workspace"
    SLACK = "slack"
    GITHUB = "github"
