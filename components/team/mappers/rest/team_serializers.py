"""DRF serializers for the team bounded context.

Moved from apps/team/serializers.py — the canonical home for team
presentation-layer serialization.

v0 (today's organic shape) + v1 (the API v1 C-contract). The v1 subclasses
override ONLY the boundary-shaped fields per the contract:

* datetimes (``created_at``) → ISO-8601 UTC ``Z`` (C4).

The plan/billing/entitlement fields were removed from this fork along with the
subscription/money domains; the ``Plan*`` serializers here are inert stubs kept
only so the workspace context's import of the symbols still resolves.
"""

from datetime import UTC, datetime

from drf_writable_nested.serializers import WritableNestedModelSerializer
from rest_framework import serializers

from components.identity.mappers.rest.identity_serializers import (
    UserSerializer,
    UserSummarySerializer,
)
from infrastructure.persistence.team.models import Invitation, Team
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import Workspace


def _iso_utc_z(dt) -> str | None:
    """C4: ISO-8601 in UTC with a ``Z`` suffix, seconds precision; null-safe.

    Mirrors the helper in ``receipts``/``budgeting`` mappers so every v1
    timestamp across contexts serializes byte-identically. Production runs
    ``USE_TZ=False`` with ``TZ=UTC`` (naive == UTC); the test settings run
    ``USE_TZ=True`` (tz-aware) — both branches are handled.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:  # naive (prod runs USE_TZ=False, TZ=UTC)
        return dt.replace(microsecond=0).isoformat() + "Z"
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# The subscription/billing/entitlement domain (``subscription.Plan``, the
# ``money`` context, and ``subscription.domain.entitlements``) was removed from
# this fork. ``PlanSerializer`` / ``PlanSerializerV1`` / ``plan_serializer_for_version``
# are retained as inert stubs ONLY so the (kept) workspace context's import of
# these symbols still resolves; they render nothing.
class PlanSerializer(serializers.Serializer):
    """Inert stub — the plan/billing domain no longer exists in this fork."""

    def to_representation(self, instance):
        return None


class PlanSerializerV1(PlanSerializer):
    """Inert v1 stub — see ``PlanSerializer``."""


def plan_serializer_for_version(version):
    """Return the inert plan serializer stub regardless of version."""
    return PlanSerializerV1 if version == "v1" else PlanSerializer


class TeamSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    members = UserSerializer(many=True, required=False)
    created_by = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field="id")
    workspace = serializers.SlugRelatedField(queryset=Workspace.objects.all(), slug_field="id")

    class Meta:
        model = Team
        fields = [
            "id",
            "workspace",
            "title",
            "kind",
            "members",
            "created_by",
            "created_at",
            "status",
            "privacy",
            "is_default",
        ]


class TeamSerializerV1(TeamSerializer):
    """v1 read shape for a team — reshapes datetimes to ISO-8601 UTC ``Z`` (C4).

    ``created_at`` is the only boundary-shaped field on the team read payload
    after the plan/billing fields were dropped in this fork.

    Read-only; never used to deserialize input.
    """

    created_at = serializers.SerializerMethodField()

    class Meta(TeamSerializer.Meta):
        pass

    def get_created_at(self, obj):
        return _iso_utc_z(getattr(obj, "created_at", None))


def team_serializer_for_version(version):
    """Team detail/list read serializer for the resolved API version.

    The ONLY place (alongside the summary helper) the team controller branches
    on version. v0 (and any unknown version) falls through to the frozen v0
    ``TeamSerializer``.
    """
    return TeamSerializerV1 if version == "v1" else TeamSerializer


class TeamSummarySerializer(serializers.ModelSerializer):
    """Lightweight team payload for login/user summary responses.

    CONSTRAINTS:
    - Excludes members and nested workspace details.
    - Provides only identifiers.
    """

    workspace_id = serializers.UUIDField(source="workspaces.id", read_only=True)

    class Meta:
        model = Team
        fields = [
            "id",
            "title",
            "kind",
            "status",
            "workspace_id",
        ]


class TeamSummarySerializerV1(TeamSummarySerializer):
    """v1 read shape for the lightweight team summary.

    After the plan/billing fields were dropped in this fork there are no
    boundary-shaped fields left to reshape. Read-only.
    """

    class Meta(TeamSummarySerializer.Meta):
        pass


def team_summary_serializer_for_version(version):
    """Team-summary read serializer for the resolved API version.

    v0 (and any unknown version) falls through to the frozen v0
    ``TeamSummarySerializer``.
    """
    return TeamSummarySerializerV1 if version == "v1" else TeamSummarySerializer


class TeamSummaryWithMembersSerializer(serializers.ModelSerializer):
    """Compact team payload with summarized members for workspace detail views."""

    members = UserSummarySerializer(many=True, read_only=True)
    workspace_id = serializers.UUIDField(source="workspaces.id", read_only=True)

    class Meta:
        model = Team
        fields = [
            "id",
            "title",
            "kind",
            "status",
            "privacy",
            "workspace_id",
            "members",
        ]


class InvitationSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    team = serializers.SlugRelatedField(queryset=Team.objects.all(), slug_field="title")

    class Meta:
        model = Invitation
        fields = [
            "id",
            "team",
            "email",
            "code",
            "status",
            "date_sent",
            "accepted_at",
        ]


class TeamMembershipSummarySerializer(serializers.ModelSerializer):
    """Lightweight representation of a user plus the teams they belong to."""

    teams = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_active",
            "avatar_url",
            "teams",
        )

    def get_teams(self, obj):
        team_lookup = self.context.get("team_lookup", {})
        teams = team_lookup.get(obj.id, [])
        formatted = []
        for team in teams:
            joined_at = team.get("joined_at")
            if isinstance(joined_at, datetime):
                joined_value = joined_at.isoformat()
            else:
                joined_value = joined_at
            formatted.append(
                {
                    "id": team.get("id"),
                    "title": team.get("title"),
                    "joined_at": joined_value,
                }
            )
        return formatted

    def get_avatar_url(self, obj):
        profile = getattr(obj, "profile", None)
        return getattr(profile, "photo_url", "") if profile else ""


class PendingInvitationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    latest_sent = serializers.DateTimeField()
    teams = serializers.ListField(child=serializers.DictField(), allow_empty=True)


class TeamActivateSerializer(serializers.Serializer):
    """Input schema for activating a team within a workspace context."""

    team_id = serializers.CharField()


class TeamInvitationRequestSerializer(serializers.Serializer):
    """Input schema for inviting a member to a team."""

    email = serializers.EmailField(required=False)
    emails = serializers.ListField(child=serializers.EmailField(), required=False)
    user_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    workspace = serializers.CharField()
    team = serializers.CharField(required=False)

    def validate(self, attrs):
        email = attrs.get("email")
        emails = attrs.get("emails") or []
        user_ids = attrs.get("user_ids") or []
        if not email and not emails and not user_ids:
            raise serializers.ValidationError("Provide email, emails, or user_ids.")
        return attrs


class InvitationAcceptSerializer(serializers.Serializer):
    """Input schema for accepting a team invitation."""

    code = serializers.CharField()
