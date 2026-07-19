"""Constants shared across the AI teammate domain.

Phase 5 of the Agents-as-Teammates migration retired the
``AI_ACTION_*`` + ``AI_ACTOR_*`` constants along with the AIAction
model — keep only the teammate-lifecycle values still consumed by
``actions_service.AIActionService.ensure_teammate``.
"""

AI_TEAMMATE_STATUS_ACTIVE = 'active'
AI_TEAMMATE_STATUS_PAUSED = 'paused'
AI_TEAMMATE_STATUS_DISABLED = 'disabled'

DEFAULT_TEAMMATE_EMAIL_DOMAIN = 'ai-teammate.local'
DEFAULT_TEAMMATE_PASSWORD_LENGTH = 32
