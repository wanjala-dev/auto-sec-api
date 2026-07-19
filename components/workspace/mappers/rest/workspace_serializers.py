from drf_writable_nested.serializers import WritableNestedModelSerializer
from rest_framework import serializers

from components.identity.mappers.rest.identity_serializers import LeanUserSerializer
from components.shared_platform.mappers.rest.core_serializers import (
    ProjectSimpleSerializer,
    SimpleContributionMeansSerializer,
    TaskSimpleSerializer,
)
from infrastructure.persistence.notifications.userpreferences.models import (
    FINANCIAL_REPORT_FREQUENCY_CHOICES,
    FINANCIAL_REPORT_FREQUENCY_DEFAULT,
    FINANCIAL_REPORT_FREQUENCY_KEY,
    FINANCIAL_REPORT_INTERVAL_UNIT_CHOICES,
    FINANCIAL_REPORT_INTERVAL_UNIT_KEY,
    FINANCIAL_REPORT_INTERVAL_VALUE_KEY,
    WORKSPACE_NOTIFICATION_DEFAULTS,
    WorkspacePreference,
)
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import (
    Action,
    ContributionMeans,
    SubCategory,
    Tag,
    Workspace,
    WorkspaceCard,
    WorkspaceCategory,
    WorkspaceComment,
    WorkspaceOperations,
)


class SubCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubCategory
        fields = ["id", "name"]


class WorkspaceCategorySerializer(serializers.ModelSerializer):
    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceCategory
        fields = ["id", "name", "subcategories"]

    def get_subcategories(self, obj):
        workspace = self.context.get("workspace")
        if workspace:
            subcategory_ids = workspace.workspace_subcategories.values_list("id", flat=True)
            return SubCategorySerializer(
                SubCategory.objects.filter(id__in=subcategory_ids, workspaces=workspace, category=obj), many=True
            ).data
        return []


class TagSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    class Meta:
        ref_name = "tags_workspaces"
        model = Tag
        fields = ["name"]


class WorkspaceCommentSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    author = serializers.SlugRelatedField(read_only=True, slug_field="id")
    likes = LeanUserSerializer(many=True, read_only=True)
    dislikes = LeanUserSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    workspace = serializers.SlugRelatedField(queryset=Workspace.objects.all(), slug_field="id")
    parent = serializers.SlugRelatedField(
        queryset=WorkspaceComment.objects.all(), slug_field="id", required=False, allow_null=True
    )

    class Meta:
        model = WorkspaceComment
        depth = 4
        fields = [
            "pk",
            "comment",
            "workspace",
            "privacy",
            "created_on",
            "author",
            "likes",
            "dislikes",
            "parent",
            "tags",
        ]
        read_only_fields = ["tags"]


class WorkspaceCommentGetSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    author = LeanUserSerializer()
    likes = LeanUserSerializer(many=True, read_only=True)
    dislikes = LeanUserSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    workspace = serializers.SlugRelatedField(queryset=Workspace.objects.all(), slug_field="id")
    parent = serializers.SlugRelatedField(
        queryset=WorkspaceComment.objects.all(), slug_field="id", required=False, allow_null=True
    )

    class Meta:
        model = WorkspaceComment
        depth = 4
        fields = [
            "pk",
            "comment",
            "workspace",
            "privacy",
            "created_on",
            "author",
            "likes",
            "dislikes",
            "parent",
            "tags",
        ]
        read_only_fields = ["tags"]


class WorkspaceOperationsSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    class Meta:
        model = WorkspaceOperations
        fields = ["id", "name", "checked", "text"]


class WorkspaceSerializer(WritableNestedModelSerializer):
    followers = serializers.SerializerMethodField()
    operations = serializers.SerializerMethodField()
    workspace_owner = serializers.ReadOnlyField(source="workspace_owner.id")
    ai_teammate_display_name = serializers.SerializerMethodField()
    orchestrator_enabled = serializers.SerializerMethodField()
    workspace_subcategories = serializers.PrimaryKeyRelatedField(
        queryset=SubCategory.objects.all(), many=True, required=False
    )
    workspace_categories = serializers.PrimaryKeyRelatedField(
        queryset=WorkspaceCategory.objects.all(), many=True, required=False
    )

    class Meta:
        model = Workspace
        depth = 0
        fields = [
            "id",
            "workspace_type",
            "workspace_name",
            "workspace_owner",
            "is_verified",
            "is_active",
            "notifications_enabled",
            "created_at",
            "updated_at",
            "workspace_story",
            "vision",
            "mission",
            "goals",
            "contact_email",
            "phone",
            "country",
            "location",
            "street_address",
            "city",
            "state_region",
            "postal_code",
            "photo_url",
            "cover_photo_url",
            "privacy",
            "tags",
            "start_date",
            "end_date",
            "status",
            "followers",
            "operations",
            "workspace_categories",
            "workspace_subcategories",
            "ai_teammate_display_name",
            "ai_teammate_enabled",
            "orchestrator_enabled",
        ]
        read_only_fields = []

    def _get_nested_serializer_context(self):
        """
        Ensure nested serializers always receive a request object so hyperlinked
        fields (e.g., in LeanUserSerializer) can build URLs without raising errors.
        """
        context = dict(getattr(self, "context", {}) or {})
        if "request" not in context or context["request"] is None:
            view = context.get("view")
            if view is not None and getattr(view, "request", None):
                context["request"] = view.request
        context.setdefault("request", None)
        return context

    def get_followers(self, obj):
        return LeanUserSerializer(
            obj.followers.all(),
            many=True,
            context=self._get_nested_serializer_context(),
        ).data

    def get_operations(self, obj):
        from components.workspace.mappers.rest.workspace_serializers import WorkspaceOperationsSerializer

        return WorkspaceOperationsSerializer(
            obj.operations.all(),
            many=True,
            context=self._get_nested_serializer_context(),
        ).data

    def get_ai_teammate_display_name(self, obj):
        # Route through the central resolver so all surfaces (chat header,
        # task-card chip, audit copy, LLM prompt) share one default.
        from components.agents.infrastructure.services.agent_permissions_service import (
            resolve_ai_teammate_alias,
        )

        return resolve_ai_teammate_alias(obj)

    def get_orchestrator_enabled(self, obj):
        return getattr(obj, "ai_teammate_enabled", False)

    def create(self, validated_data):
        # Delegate to service for workspace creation with proper ORM isolation
        from components.shared_platform.application.facades.feature_flags_facade import is_feature_enabled

        workspace_categories_data = validated_data.pop("workspace_categories", [])
        workspace_subcategories_data = validated_data.pop("workspace_subcategories", [])

        request = self.context.get("request") if hasattr(self, "context") else None
        user = getattr(request, "user", None) if request else None

        # Personal workspaces are gated per-user by feature.personal_space
        # (globally off in prod). Without the flag the create endpoint cannot
        # mint a personal-type workspace: workspace_type is forced to teamspace.
        # Mirrors the onboarding bootstrap gate in workspace_bootstrap.py so both
        # creation paths agree.
        if not is_feature_enabled("feature.personal_space", user=user):
            validated_data["workspace_type"] = Workspace.TEAMSPACE

        # Create workspace using deferred ORM call
        from infrastructure.persistence.workspaces.models import Workspace as WS

        workspace = WS.objects.create(**validated_data)

        if workspace_categories_data:
            workspace.workspace_categories.set(workspace_categories_data)
        if workspace_subcategories_data:
            workspace.workspace_subcategories.set(workspace_subcategories_data)

        return workspace

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        representation["workspace_subcategories"] = list(
            instance.workspace_subcategories.all().values_list("id", flat=True)
        )
        representation["workspace_categories"] = list(instance.workspace_categories.all().values_list("id", flat=True))

        return representation


class WorkspaceGetSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    followers = LeanUserSerializer(many=True, required=False)
    workspace_owner = LeanUserSerializer()
    operations = WorkspaceOperationsSerializer(many=True, required=False)
    workspace_categories = WorkspaceCategorySerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, required=False)
    associated_users = LeanUserSerializer(many=True, read_only=True)
    contribution_means = SimpleContributionMeansSerializer(many=True, read_only=True)
    ai_teammate_display_name = serializers.SerializerMethodField()
    orchestrator_enabled = serializers.SerializerMethodField()
    # Viewer role — "owner", "admin", "contributor", "sponsor", or
    # "personal". Matches what the user-summary endpoint returns, so the
    # frontend can use a single admin-bypass check regardless of which
    # endpoint loaded the seed.
    role = serializers.SerializerMethodField()
    # Viewer relationship — "member" or "follower". Mirrors the field
    # emitted on /identity/me/summary/ so the workspace detail page can
    # distinguish a member from a follower without round-tripping the
    # summary endpoint. Returns None for anonymous requests.
    relationship = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        depth = 4
        fields = [
            "id",
            "workspace_type",
            "workspace_name",
            "workspace_owner",
            "is_verified",
            "is_active",
            "created_at",
            "updated_at",
            "workspace_categories",
            "workspace_story",
            # Mission / vision / goals / contact details / address — read
            # back so the Workspace + Address tabs can re-hydrate the form
            # after a save. Mission / vision / contact_email were missing
            # here previously, which is why those fields never round-tripped
            # cleanly through the settings flow.
            "vision",
            "mission",
            "goals",
            "contact_email",
            "phone",
            "country",
            "location",
            "street_address",
            "city",
            "state_region",
            "postal_code",
            "photo_url",
            "cover_photo_url",
            "privacy",
            "start_date",
            "end_date",
            "status",
            "tags",
            "followers",
            "operations",
            "associated_users",
            "contribution_means",
            "ai_teammate_display_name",
            "ai_teammate_enabled",
            "orchestrator_enabled",
            "notifications_enabled",
            "role",
            "relationship",
        ]

    def get_ai_teammate_display_name(self, obj):
        # Route through the central resolver so all surfaces (chat header,
        # task-card chip, audit copy, LLM prompt) share one default.
        from components.agents.infrastructure.services.agent_permissions_service import (
            resolve_ai_teammate_alias,
        )

        return resolve_ai_teammate_alias(obj)

    def get_orchestrator_enabled(self, obj):
        return getattr(obj, "ai_teammate_enabled", False)

    def get_role(self, obj):
        """Resolve the requesting user's role in this workspace.

        Mirrors the logic in ``identity/api/controller.py`` so the detail
        endpoint's ``role`` field matches what the user-summary endpoint
        returns. Returns None for anonymous requests.

        Reads ``WorkspaceMembership.role`` + ``.persona`` (the canonical
        ADR 0002 RBAC + experience signals) instead of the legacy
        team-creator heuristic.
        """
        request = self.context.get("request") if hasattr(self, "context") else None
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None
        from components.identity.domain.policies.workspace_role_policy import (
            resolve_workspace_role,
        )
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        is_owner = obj.workspace_owner_id == user.id
        is_personal = obj.workspace_type == "personal" and is_owner
        membership = (
            WorkspaceMembership.objects.filter(
                workspace_id=obj.id,
                user_id=user.id,
                status=WorkspaceMembership.Status.ACTIVE,
                is_impersonation=False,
            )
            .only("role", "persona")
            .first()
        )
        return resolve_workspace_role(
            is_owner=is_owner,
            is_personal_workspace=is_personal,
            membership_role=membership.role if membership else None,
            membership_persona=membership.persona if membership else None,
        ).role

    def get_relationship(self, obj):
        """Distinguish member from follower for the requesting user.

        Mirrors the ``relationship`` field on
        ``/identity/me/summary/`` so the workspace detail endpoint
        emits the same discriminator. "member" means the user owns
        the workspace, has a team membership, or has an active
        WorkspaceMembership row; "follower" means they only appear
        in ``Workspace.followers``. Returns None for anonymous
        requests.
        """
        request = self.context.get("request") if hasattr(self, "context") else None
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        if obj.workspace_owner_id == user.id:
            return "member"
        is_team_member = obj.workspace_teams.filter(members=user.id).exists()
        if is_team_member:
            return "member"
        has_membership = WorkspaceMembership.objects.filter(
            workspace_id=obj.id,
            user_id=user.id,
            status=WorkspaceMembership.Status.ACTIVE,
            is_impersonation=False,
        ).exists()
        if has_membership:
            return "member"
        return "follower"


class WorkspaceContributionsMeansSerializer(serializers.ModelSerializer):
    workspaces = WorkspaceGetSerializer(many=True, read_only=True)
    projects = ProjectSimpleSerializer(many=True, read_only=True)
    tasks = TaskSimpleSerializer(many=True, read_only=True)

    class Meta:
        model = ContributionMeans
        fields = [
            "id",
            "workspaces",
            "projects",
            "tasks",
            "name",
            "icon",
            "description",
            "is_active",
            "order",
            "created_at",
            "updated_at",
        ]


# Add this new serializer class
class WorkspaceContributionMeansAssignmentSerializer(serializers.Serializer):
    workspace = serializers.UUIDField(help_text="UUID of the workspace to assign contribution means to")
    means = serializers.ListField(
        child=serializers.IntegerField(), help_text="List of contribution means IDs to assign to the workspace"
    )

    def validate_means(self, value):
        # Verify that all means exist using lazy import
        from infrastructure.persistence.workspaces.models import ContributionMeans as CM

        means_ids = set(value)
        existing_means = set(CM.objects.filter(id__in=means_ids).values_list("id", flat=True))
        if means_ids != existing_means:
            raise serializers.ValidationError("One or more contribution means do not exist")
        return value

    def validate_workspace(self, value):
        # Verify that the workspace exists using lazy import
        from infrastructure.persistence.workspaces.models import Workspace as WS

        if not WS.objects.filter(id=value).exists():
            raise serializers.ValidationError("Workspace does not exist")
        return value


class WorkspaceSetupCheckSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    is_complete = serializers.BooleanField()
    detail = serializers.CharField(allow_blank=True)


class WorkspaceSetupRecommendationSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    severity = serializers.CharField()
    scope = serializers.CharField()


class WorkspaceSetupStatusSerializer(serializers.Serializer):
    workspace = serializers.UUIDField()
    workspace_name = serializers.CharField()
    is_complete = serializers.BooleanField()
    checks = WorkspaceSetupCheckSerializer(many=True)
    pending = serializers.ListField(child=serializers.CharField())
    recommendations = WorkspaceSetupRecommendationSerializer(many=True, allow_empty=True)


class WorkspacePutSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    followers = LeanUserSerializer(many=True, required=False)
    tags = TagSerializer(many=True, required=False)
    workspace_owner = serializers.ReadOnlyField(source="workspace_owner.id")
    operations = WorkspaceOperationsSerializer(many=True, required=False)
    workspace_categories = serializers.PrimaryKeyRelatedField(
        queryset=WorkspaceCategory.objects.all(), many=True, allow_null=True
    )

    class Meta:
        model = Workspace
        fields = [
            "id",
            "workspace_name",
            "workspace_owner",
            "is_verified",
            "is_active",
            "created_at",
            "updated_at",
            "workspace_categories",
            "workspace_story",
            # Mission / vision / goals were missing from this serializer
            # which made the existing Settings -> Workspace save a no-op
            # for those fields. Adding them here unblocks the new Goals &
            # Objectives field and also fixes the pre-existing silent-drop
            # for vision / mission / contact_email.
            "vision",
            "mission",
            "goals",
            "contact_email",
            "phone",
            "country",
            "location",
            "street_address",
            "city",
            "state_region",
            "postal_code",
            "photo_url",
            "cover_photo_url",
            "privacy",
            "tags",
            "start_date",
            "end_date",
            "status",
            "followers",
            "operations",
            "notifications_enabled",
            "ai_teammate_enabled",
        ]

    def update(self, instance, validated_data):
        # Detect AI enable transition (false -> true) BEFORE the update
        was_ai_enabled = bool(getattr(instance, "ai_teammate_enabled", False))
        will_be_ai_enabled = bool(validated_data.get("ai_teammate_enabled", was_ai_enabled))
        ai_just_enabled = (not was_ai_enabled) and will_be_ai_enabled

        instance = super().update(instance, validated_data)

        # Kick off the RAG backfill the moment AI is enabled so the workspace
        # is immediately searchable in chat. The task is gated on
        # ai_teammate_enabled internally as a safety net.
        if ai_just_enabled:
            try:
                from components.knowledge.infrastructure.tasks.embedding_tasks import (
                    create_embeddings_for_workspace,
                )

                create_embeddings_for_workspace.delay(str(instance.id))
            except Exception as exc:
                import logging

                logging.getLogger(__name__).warning(
                    f"Failed to enqueue embeddings backfill for workspace {instance.id}: {exc}"
                )

        return instance


WORKSPACE_PREFERENCE_FIELDS = tuple(WORKSPACE_NOTIFICATION_DEFAULTS.keys())


class WorkspacePreferenceSerializer(serializers.ModelSerializer):
    workspace = serializers.SlugRelatedField(queryset=Workspace.objects.all(), slug_field="id")
    settings = serializers.DictField(child=serializers.JSONField(), required=False)
    financial_report_frequency = serializers.ChoiceField(
        choices=FINANCIAL_REPORT_FREQUENCY_CHOICES,
        required=False,
    )
    financial_report_interval_unit = serializers.ChoiceField(
        choices=FINANCIAL_REPORT_INTERVAL_UNIT_CHOICES,
        required=False,
        allow_null=True,
    )
    financial_report_interval_value = serializers.IntegerField(
        required=False,
        min_value=1,
    )
    donations = serializers.BooleanField(required=False)
    expenses = serializers.BooleanField(required=False)
    income = serializers.BooleanField(required=False)
    story = serializers.BooleanField(required=False)
    sources = serializers.BooleanField(required=False)
    team = serializers.BooleanField(required=False)
    budget = serializers.BooleanField(required=False)
    activities = serializers.BooleanField(required=False)
    gallery = serializers.BooleanField(required=False)
    comments = serializers.BooleanField(required=False)
    farming = serializers.BooleanField(required=False)
    sponsorship = serializers.BooleanField(required=False)
    payroll = serializers.BooleanField(required=False)
    fundraising = serializers.BooleanField(required=False)
    books_records = serializers.BooleanField(required=False)

    class Meta:
        model = WorkspacePreference
        fields = [
            "id",
            "workspace",
            "settings",
            "financial_report_frequency",
            "financial_report_interval_unit",
            "financial_report_interval_value",
        ] + list(WORKSPACE_PREFERENCE_FIELDS)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        merged = instance.get_settings()
        data["settings"] = merged
        frequency = merged.get(FINANCIAL_REPORT_FREQUENCY_KEY, FINANCIAL_REPORT_FREQUENCY_DEFAULT)
        data["settings"][FINANCIAL_REPORT_FREQUENCY_KEY] = frequency
        data["financial_report_frequency"] = frequency
        interval_unit = merged.get(FINANCIAL_REPORT_INTERVAL_UNIT_KEY)
        interval_value = merged.get(FINANCIAL_REPORT_INTERVAL_VALUE_KEY)
        data["financial_report_interval_unit"] = interval_unit
        data["financial_report_interval_value"] = interval_value
        data["settings"][FINANCIAL_REPORT_INTERVAL_UNIT_KEY] = interval_unit
        data["settings"][FINANCIAL_REPORT_INTERVAL_VALUE_KEY] = interval_value
        for key in WORKSPACE_PREFERENCE_FIELDS:
            data[key] = merged.get(key, WORKSPACE_NOTIFICATION_DEFAULTS.get(key, False))
        return data

    def create(self, validated_data):
        settings_payload = self._extract_settings(validated_data)
        workspace = validated_data["workspace"]
        preference, _ = WorkspacePreference.objects.get_or_create(workspace=workspace)
        if settings_payload:
            preference.update_settings(settings_payload, commit=True)
        return preference

    def update(self, instance, validated_data):
        settings_payload = self._extract_settings(validated_data)
        if settings_payload:
            instance.update_settings(settings_payload, commit=False)
        if "workspace" in validated_data:
            instance.workspace = validated_data["workspace"]
        instance.save()
        return instance

    def _extract_settings(self, validated_data):
        settings = dict(validated_data.pop("settings", {}) or {})
        if "financial_report_frequency" in validated_data:
            settings[FINANCIAL_REPORT_FREQUENCY_KEY] = validated_data.pop("financial_report_frequency")
        if "financial_report_interval_unit" in validated_data:
            settings[FINANCIAL_REPORT_INTERVAL_UNIT_KEY] = validated_data.pop("financial_report_interval_unit")
        if "financial_report_interval_value" in validated_data:
            settings[FINANCIAL_REPORT_INTERVAL_VALUE_KEY] = validated_data.pop("financial_report_interval_value")
        for key in WORKSPACE_PREFERENCE_FIELDS:
            if key in validated_data:
                settings[key] = validated_data.pop(key)
        clean_settings = {}
        for key, value in settings.items():
            if key in WORKSPACE_NOTIFICATION_DEFAULTS:
                clean_settings[key] = bool(value)
            else:
                clean_settings[key] = value
        return clean_settings


## Removed legacy IncomeSerializer and ExpensesSerializer in favor of budget app serializers
class ActionSerializer(WritableNestedModelSerializer, serializers.ModelSerializer):
    likes = LeanUserSerializer(many=True, required=False)
    owner = serializers.SlugRelatedField(queryset=CustomUser.objects.all(), slug_field="id")
    workspace = serializers.SlugRelatedField(queryset=Workspace.objects.all(), slug_field="id")

    class Meta:
        model = Action
        depth = 2
        fields = ("id", "url", "owner", "privacy", "likes", "workspace", "dislikes", "title", "created_date")


class FiltersSerializers(serializers.Serializer):
    WorkspaceComment = WorkspaceCommentSerializer(read_only=True, many=True)
    Workspace = WorkspaceSerializer(read_only=True, many=True)


class WorkspaceCardSerializer(serializers.ModelSerializer):
    workspace = serializers.SlugRelatedField(queryset=Workspace.objects.all(), slug_field="id")

    class Meta:
        model = WorkspaceCard
        fields = ["id", "workspace", "name", "checked", "text", "photo_url"]
