# Team Bounded Context - Commands Reference

Quick lookup for all command DTOs in the Team bounded context.

## Command Map

| Command | Use Case | Endpoint | Immutable |
|---------|----------|----------|-----------|
| `CreateTeamCommand` | CreateTeamUseCase | POST `/teams/` | ✓ |
| `UpdateTeamCommand` | UpdateTeamUseCase | PATCH `/teams/` | ✓ |
| `ActivateTeamContextCommand` | ActivateTeamContextUseCase | POST `/teams/activate/` | ✓ |
| `AcceptTeamInvitationCommand` | AcceptTeamInvitationUseCase | POST `/invitations/accept/` | ✓ |
| `ProcessTeamInvitationBatchCommand` | ProcessTeamInvitationBatchUseCase | POST `/invitations/batch/` | ✓ |
| `PrepareTeamInvitationCommand` | PrepareTeamInvitationUseCase | Internal | ✓ |
| `IssueTeamInvitationCommand` | IssueTeamInvitationUseCase | Internal | ✓ |
| `SyncWorkspaceAiTeammateCommand` | SyncWorkspaceAiTeammateUseCase | Internal | ✓ |

## Quick Usage Examples

### Creating a Team
```python
from components.team.application.commands import CreateTeamCommand
from components.team.application.service import TeamService

service = TeamService()
command = CreateTeamCommand(
    title="Engineering",
    plan_id=1,
    workspace_id=uuid.uuid4(),
    actor=request.user
)
team = service.create_team(command)
```

### Activating Team Context
```python
from components.team.application.commands import ActivateTeamContextCommand

command = ActivateTeamContextCommand(
    team_id=42,
    actor_id=request.user.id,
    is_staff=request.user.is_staff,
    is_superuser=request.user.is_superuser
)
team = service.activate_team_context(command)
```

### Accepting an Invitation
```python
from components.team.application.commands import AcceptTeamInvitationCommand

command = AcceptTeamInvitationCommand(
    code=request.data.get('code'),
    actor=request.user
)
invitation = service.accept_team_invitation(command)
```

### Batch Processing Invitations
```python
from components.team.application.commands import ProcessTeamInvitationBatchCommand

command = ProcessTeamInvitationBatchCommand(
    actor=request.user,
    workspace_id=workspace_uuid,
    team_id=team_id,
    emails=['user1@example.com', 'user2@example.com'],
    user_ids=[],
    request=request,
    is_staff=request.user.is_staff,
    is_superuser=request.user.is_superuser
)
result = service.process_team_invitation_batch(command)
```

## Command Attributes

### CreateTeamCommand
- `title: str` - Team name
- `plan_id: int` - Billing plan ID
- `workspace_id: object` - UUID of workspace
- `actor: object` - User instance performing action

### UpdateTeamCommand
- `actor: object` - User instance
- `validated_data: dict` - Pre-validated fields from serializer
- `is_staff: bool` - Actor staff status (optional)
- `is_superuser: bool` - Actor superuser status (optional)

### ActivateTeamContextCommand
- `team_id: object` - Team ID (int)
- `actor_id: object` - User ID
- `is_staff: bool` - Actor staff status (optional)
- `is_superuser: bool` - Actor superuser status (optional)

### AcceptTeamInvitationCommand
- `code: str` - Invitation code
- `actor: object` - User instance

### ProcessTeamInvitationBatchCommand
- `actor: object` - User instance
- `workspace_id: object` - UUID
- `team_id: object` - Team ID
- `emails: list[str] | None` - Email addresses to invite
- `user_ids: list | None` - Existing user IDs
- `request: object | None` - HTTP request (optional)
- `is_staff: bool` - Actor staff status (optional)
- `is_superuser: bool` - Actor superuser status (optional)

### PrepareTeamInvitationCommand
- `workspace_id: object` - UUID
- `team_id: object` - Team ID
- `actor: object` - User instance
- `emails: list[str] | None` - Emails to validate
- `user_ids: list | None` - User IDs to validate
- `is_staff: bool` - Actor staff status (optional)
- `is_superuser: bool` - Actor superuser status (optional)

### IssueTeamInvitationCommand
- `workspace: object` - Workspace object
- `team: object` - Team object
- `invitee: object` - User being invited
- `email: str` - Invitee email
- `actor_id: object` - Issuing user ID

### SyncWorkspaceAiTeammateCommand
- `workspace: object` - Workspace to sync

## Imports

```python
# Import individual commands
from components.team.application.commands import CreateTeamCommand

# Import all commands
from components.team.application.commands import *

# Import specific commands
from components.team.application.commands import (
    CreateTeamCommand,
    UpdateTeamCommand,
    ActivateTeamContextCommand,
    AcceptTeamInvitationCommand,
    ProcessTeamInvitationBatchCommand,
)
```

## Testing

All commands are frozen dataclasses and can be easily instantiated in tests:

```python
from components.team.application.commands import CreateTeamCommand
from unittest.mock import Mock

command = CreateTeamCommand(
    title="Test Team",
    plan_id=1,
    workspace_id=Mock(),
    actor=Mock()
)
assert command.title == "Test Team"
# Cannot modify: command.title = "New Name"  # TypeError
```
