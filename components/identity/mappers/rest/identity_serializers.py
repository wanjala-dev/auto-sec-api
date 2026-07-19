from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from components.identity.infrastructure.adapters.workspace_bootstrap import (
    ensure_user_workspace_context,
    should_bootstrap_workspace,
)
from components.shared_platform.mappers.rest.core_serializers import (
    ProjectSimpleSerializer,
    SimpleWorkspaceSerializer,
    TaskSimpleSerializer,
)
from components.workspace.infrastructure.adapters.workspace_utils import ensure_workspace_follower
from components.workspace.mappers.rest.countries_serializers import CountrySerializer
from infrastructure.persistence.countries.models import Country
from infrastructure.persistence.users.models import ContributorProfile, CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import ContributionMeans, Workspace


# Create a local serializer for ContributionMeans to avoid circular imports
class ContributionMeansSerializer(serializers.ModelSerializer):
    workspaces = SimpleWorkspaceSerializer(many=True, read_only=True)
    projects = ProjectSimpleSerializer(many=True, read_only=True)
    tasks = TaskSimpleSerializer(many=True, read_only=True)

    class Meta:
        model = ContributionMeans
        fields = [
            "id",
            "name",
            "icon",
            "description",
            "is_active",
            "order",
            "created_at",
            "updated_at",
            "workspaces",
            "projects",
            "tasks",
        ]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(max_length=68, min_length=6, write_only=True)
    default_error_messages = {"username": "The username should only contain alphanumeric characters"}

    class Meta:
        model = CustomUser
        fields = ["email", "username", "password"]

    def validate(self, attrs):
        email = attrs.get("email", "")
        username = attrs.get("username", "")
        if not username.isalnum():
            raise serializers.ValidationError(self.default_error_messages)
        return attrs

    def create(self, validated_data):
        """Delegate user creation to repository via context-injected service."""
        service = self.context.get("service") if self.context else None
        if service:
            # Use repository directly via service
            repository = service.identity_provider.build_user_repository()
            user_entity = repository.create_user(
                username=validated_data["username"],
                email=validated_data["email"],
                password=validated_data["password"],
            )
            # Return ORM instance for DRF serialization
            return CustomUser.objects.get(id=user_entity.id)
        # Fallback for backwards compatibility
        return CustomUser.objects.create_user(**validated_data)


class EmailVerificationSerializer(serializers.ModelSerializer):
    token = serializers.CharField(max_length=555)

    class Meta:
        model = CustomUser
        fields = ["token"]


class UserProfileSerializer(serializers.ModelSerializer):
    following_count = serializers.IntegerField(source="get_following_count", read_only=True)
    followers_count = serializers.IntegerField(source="get_followers_count", read_only=True)
    active_workspace = serializers.SerializerMethodField(read_only=True)
    country = CountrySerializer(required=False)

    class Meta:
        model = UserProfile
        fields = (
            "title",
            "dob",
            "address",
            "about",
            "country",
            "zip",
            "photo_url",
            "banner_photo_url",
            "city",
            "name",
            "followers",
            "followers_count",
            "following_count",
            "active_workspace",
            "active_workspace_id",
        )

    def get_active_workspace(self, obj) -> dict[str, str] | None:
        if not obj.active_workspace_id:
            return None
        # ``active_workspace_id`` is a plain UUIDField (not a FK), so this
        # lookup cannot be ``select_related``-ed away. Memoise per serializer
        # context instead: on list endpoints that embed many users (team
        # members, news authors, …) the same handful of workspaces would
        # otherwise be re-fetched once per rendered profile — an N+1.
        memo = None
        if isinstance(self.context, dict):
            memo = self.context.setdefault("_active_workspace_memo", {})
            key = str(obj.active_workspace_id)
            if key in memo:
                return memo[key]
        result = self._fetch_active_workspace(obj)
        if memo is not None:
            memo[str(obj.active_workspace_id)] = result
        return result

    def _fetch_active_workspace(self, obj) -> dict[str, str] | None:
        # Delegate workspace fetch to service via context
        service = self.context.get("service") if self.context else None
        if service:
            return service.get_workspace(obj.active_workspace_id)
        # Fallback for backwards compatibility (e.g., in tests)
        try:
            workspace = Workspace.objects.get(id=obj.active_workspace_id)
            return {"id": str(workspace.id), "workspace_name": workspace.workspace_name, "icon": workspace.photo_url}
        except Workspace.DoesNotExist:
            return None

    def update(self, instance, validated_data):
        active_workspace_value = validated_data.get("active_workspace_id", serializers.empty)
        instance = super().update(instance, validated_data)
        if active_workspace_value not in (serializers.empty, None, ""):
            # Delegate workspace follower relationship to service via context
            service = self.context.get("service") if self.context else None
            if service:
                service.ensure_workspace_follower(
                    workspace_id=active_workspace_value,
                    user_id=instance.user_id,
                )
            else:
                # Fallback for backwards compatibility
                try:
                    workspace = Workspace.objects.get(id=active_workspace_value)
                except Workspace.DoesNotExist:
                    workspace = None
                if workspace:
                    ensure_workspace_follower(workspace, instance.user)
        return instance


class UserProfileSummarySerializer(serializers.ModelSerializer):
    """Reduced profile payload for login/user summary responses.

    CONSTRAINTS:
    - Avoid nested objects or follow/follower counts.
    - Do not resolve active workspace details here.
    """

    class Meta:
        model = UserProfile
        fields = (
            "title",
            "photo_url",
            "banner_photo_url",
            "city",
            "name",
            "active_workspace_id",
            "active_team_id",
        )


class UserSerializerUUID(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["pk"]


class LeanUserSerializer(serializers.ModelSerializer):
    """Minimal user payload for nested embedding in list/detail responses.

    Use when a parent serializer references a user but only needs identity
    fields for display — no workspaces, sectors, profile, or contributor
    profile. Each of those fields on the full UserSerializer fires its own
    ORM query per row, which explodes paginated list endpoints (a 9-row
    transaction page fans out to 50+ queries).
    """

    class Meta:
        model = CustomUser
        fields = ("id", "email", "username", "first_name", "last_name")


class ContributorProfileSerializer(serializers.ModelSerializer):
    contribution_means = ContributionMeansSerializer(many=True, read_only=True)
    contribution_means_input = serializers.ListField(child=serializers.CharField(), write_only=True, required=False)
    contribution_methods_input = serializers.ListField(child=serializers.CharField(), write_only=True, required=False)
    preferred_locations = CountrySerializer(many=True, read_only=True)

    # Writable input fields
    preferred_locations_input = serializers.ListField(child=serializers.CharField(), write_only=True, required=False)

    class Meta:
        model = ContributorProfile
        fields = (
            "preferred_locations",
            "contribution_means",
            "preferred_locations_input",
            "contribution_means_input",
            "contribution_methods_input",
        )
        read_only_fields = ("preferred_locations", "contribution_means")

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        # Ensure contribution_means are included in the response
        representation["contribution_means"] = ContributionMeansSerializer(
            instance.contribution_means.all(), many=True
        ).data
        return representation

    def create(self, validated_data):
        preferred_locations_data = validated_data.pop("preferred_locations_input", [])
        contribution_means_data = validated_data.pop("contribution_means_input", [])
        contribution_methods_data = validated_data.pop("contribution_methods_input", [])

        contributor_profile = ContributorProfile.objects.create(**validated_data)

        for location_name in preferred_locations_data:
            country, _ = Country.objects.get_or_create(name=location_name)
            contributor_profile.preferred_locations.add(country)

        # Use either contribution_means_data or contribution_methods_data
        contribution_data = contribution_means_data or contribution_methods_data
        # Convert string IDs to ContributionMeans objects
        contribution_means_objects = ContributionMeans.objects.filter(id__in=contribution_data)
        contributor_profile.contribution_means.set(contribution_means_objects)

        return contributor_profile

    def update(self, instance, validated_data):
        preferred_locations_data = validated_data.pop("preferred_locations_input", None)
        contribution_means_data = validated_data.pop("contribution_means_input", None)
        contribution_methods_data = validated_data.pop("contribution_methods_input", None)

        # Update the CustomUser fields
        instance = super().update(instance, validated_data)

        # Handle preferred_locations (both add and remove)
        if preferred_locations_data is not None:
            # Get the new list of countries from the input
            new_countries = [
                Country.objects.get_or_create(name=location_name)[0] for location_name in preferred_locations_data
            ]

            # Replace the old set of preferred locations with the new one
            instance.preferred_locations.set(new_countries)

        # Handle contribution_means (both add and remove)
        # Use either contribution_means_data or contribution_methods_data
        contribution_data = contribution_means_data or contribution_methods_data
        if contribution_data is not None:
            # Convert string IDs to ContributionMeans objects
            contribution_means_objects = ContributionMeans.objects.filter(id__in=contribution_data)
            instance.contribution_means.set(contribution_means_objects)

        return instance


class UserPatchSerializer(serializers.HyperlinkedModelSerializer):
    profile = UserProfileSerializer(required=False)
    contributor_profile = ContributorProfileSerializer(required=False)
    # Optional name the user chose during onboarding. Used only when a workspace
    # is bootstrapped on this request; ignored for an already-onboarded user.
    workspace_name = serializers.CharField(required=False, allow_blank=True, write_only=True, max_length=255)

    class Meta:
        ref_name = "users.serializers.UserSerializer"
        model = CustomUser
        extra_kwargs = {"url": {"view_name": "users-detail"}}
        fields = (
            "id",
            "url",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_onboard_complete",
            "is_contributor",
            "profile",
            "contributor_profile",
            "workspace_name",
        )
        read_only_fields = ("url",)  # Make url read-only as we are patching

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if hasattr(instance, "contributor_profile"):
            representation["contributor_profile"] = ContributorProfileSerializer(instance.contributor_profile).data
        # Re-serialize the profile field with service context if available
        if hasattr(instance, "profile") and instance.profile:
            profile_serializer = UserProfileSerializer(instance.profile, context=self.context)
            representation["profile"] = profile_serializer.data
        return representation

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", {})
        contributor_profile_data = validated_data.pop("contributor_profile", None)
        workspace_name = validated_data.pop("workspace_name", None)

        # Update CustomUser fields
        instance.email = validated_data.get("email", instance.email)
        instance.username = validated_data.get("username", instance.username)
        instance.is_onboard_complete = validated_data.get("is_onboard_complete", instance.is_onboard_complete)
        instance.is_contributor = validated_data.get("is_contributor", instance.is_contributor)
        instance.first_name = validated_data.get("first_name", instance.first_name)
        instance.last_name = validated_data.get("last_name", instance.last_name)
        instance.save()

        # Update UserProfile
        profile = getattr(instance, "profile", None)
        if profile:
            # Pass service context to nested serializer if available
            profile_context = self.context.copy() if self.context else {}
            profile_serializer = UserProfileSerializer(
                profile, data=profile_data, partial=True, context=profile_context
            )
            if profile_serializer.is_valid(raise_exception=True):
                profile_serializer.save()
        elif profile_data:
            UserProfile.objects.update_or_create(user=instance, defaults=profile_data)

        if contributor_profile_data is not None:
            contributor_profile, created = ContributorProfile.objects.get_or_create(user=instance)
            contributor_profile_serializer = ContributorProfileSerializer(
                contributor_profile, data=contributor_profile_data, partial=True
            )
            if contributor_profile_serializer.is_valid(raise_exception=True):
                contributor_profile_serializer.save()

        if instance.is_onboard_complete and should_bootstrap_workspace(instance):
            ensure_user_workspace_context(instance, create_if_missing=True, workspace_name=workspace_name)

        return instance


class UserSearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ("id", "username", "first_name", "last_name")


class UserSerializer(serializers.HyperlinkedModelSerializer):
    profile = UserProfileSerializer(required=False)
    contributor_profile = ContributorProfileSerializer(read_only=True)
    workspaces = serializers.SerializerMethodField()

    class Meta:
        ref_name = "users.serializers.UserSerializer"
        model = CustomUser
        fields = (
            "id",
            "url",
            "username",
            "updated_at",
            "created_at",
            "email",
            "first_name",
            "last_name",
            "is_onboard_complete",
            "is_contributor",
            "password",
            "profile",
            "contributor_profile",
            "workspaces",
        )
        extra_kwargs = {"password": {"write_only": True}, "url": {"view_name": "users-detail"}}

    def create(self, validated_data):
        profile_data = validated_data.pop("profile", {})
        password = validated_data.pop("password")
        user = CustomUser(**validated_data)
        user.set_password(password)
        user.save()
        UserProfile.objects.update_or_create(user=user, defaults=profile_data)
        return user

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", {})

        # Update CustomUser fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update or create UserProfile
        profile = getattr(instance, "profile", None)
        if profile:
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()
        elif profile_data:
            UserProfile.objects.update_or_create(user=instance, defaults=profile_data)

        return instance

    def to_representation(self, instance):
        """Override to pass service context to nested UserProfileSerializer."""
        representation = super().to_representation(instance)
        # Re-serialize the profile field with service context if available
        if hasattr(instance, "profile") and instance.profile:
            profile_serializer = UserProfileSerializer(instance.profile, context=self.context)
            representation["profile"] = profile_serializer.data
        return representation

    def get_workspaces(self, obj) -> list[dict[str, object]]:
        # ``get_related_workspaces_queryset()`` builds a fresh queryset per
        # user, so it cannot be prefetched from the feeding repository.
        # Memoise per serializer context: list endpoints that render the same
        # user more than once (e.g. a member sitting on several teams) would
        # otherwise re-run the workspaces query for every appearance.
        memo = None
        if isinstance(self.context, dict):
            memo = self.context.setdefault("_user_workspaces_memo", {})
            if obj.pk in memo:
                return memo[obj.pk]
        request = self.context.get("request")
        workspaces_qs = obj.get_related_workspaces_queryset()
        data = SimpleWorkspaceSerializer(workspaces_qs, many=True, context={"request": request}).data
        if memo is not None:
            memo[obj.pk] = data
        return data


class UserSummarySerializer(serializers.ModelSerializer):
    """Lightweight user payload used by login summary endpoints.

    CONSTRAINTS:
    - No nested workspaces or teams.
    - Intended for quick client bootstrapping only.
    """

    profile = UserProfileSummarySerializer(read_only=True)
    two_factor_enabled = serializers.BooleanField(read_only=True)
    two_factor_confirmed_at = serializers.DateTimeField(read_only=True)
    is_platform_admin = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = (
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "is_onboard_complete",
            "is_contributor",
            "is_platform_admin",
            "two_factor_enabled",
            "two_factor_confirmed_at",
            "profile",
        )

    def get_is_platform_admin(self, obj) -> bool:
        return bool(getattr(obj, "is_superuser", False) or getattr(obj, "is_staff", False))


class LoginDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["id", "email", "username", "is_onboard_complete", "is_contributor"]


class LoginSerializer(serializers.ModelSerializer):
    """Schema-only serializer for the login endpoint.

    NOTE: All authentication business logic (lockout, credential check,
    provider validation, OTP gating, token issuance, audit, notification)
    has been extracted into ``LoginUseCase`` and is invoked directly by
    ``LoginAPIView.post()`` via ``IdentityProvider.build_login_use_case()``.

    This serializer is retained solely for DRF/Spectacular schema generation
    and request body validation (email + password shape). The ``validate()``
    override has been removed — it was dead code.
    """

    email = serializers.EmailField(max_length=255, min_length=3)
    password = serializers.CharField(max_length=68, min_length=6, write_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "email",
            "password",
        ]


class ResetPasswordEmailRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(min_length=2)
    redirect_url = serializers.CharField(max_length=500, required=False)

    class Meta:
        fields = ["email"]


class SetNewPasswordSerializer(serializers.Serializer):
    """Schema-only serializer for the set-new-password endpoint.

    NOTE: Token validation and password setting have been extracted into
    ``SetNewPasswordUseCase`` invoked by ``SetNewPasswordAPIView.patch()``
    via ``IdentityProvider.build_set_new_password_use_case()``.

    This serializer is retained for request body validation (shape only).
    """

    password = serializers.CharField(min_length=6, max_length=68, write_only=True)
    token = serializers.CharField(min_length=1, write_only=True)
    uidb64 = serializers.CharField(min_length=1, write_only=True)

    class Meta:
        fields = ["password", "token", "uidb64"]


class LogoutSerializer(serializers.Serializer):
    """Idempotent logout payload.

    Logout is a declaration of intent. A missing, expired, or malformed
    refresh token is not an error — the user is asking to be logged out.
    Best-effort blacklist the supplied refresh token; surface the outcome
    via ``token_revoked`` so the view can audit accurately.
    """

    refresh = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    token_revoked = False

    def save(self, **kwargs):
        token_string = (self.validated_data.get("refresh") or "").strip()
        if not token_string:
            self.token_revoked = False
            return
        try:
            RefreshToken(token_string).blacklist()
            self.token_revoked = True
        except TokenError:
            self.token_revoked = False


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)
    confirm_password = serializers.CharField(required=True)


# ────────────────────────────────────────────────────────────────────────────
# Social Auth Serializers (migrated from apps/social_auth/serializers.py)
# ────────────────────────────────────────────────────────────────────────────


class GoogleSocialAuthSerializer(serializers.Serializer):
    """Input shape only. All verification + user resolution + token
    issuance lives in ``AuthenticateWithGoogleUseCase`` behind ports
    (see ``GoogleSocialAuthView``). Keeping business logic out of the
    serializer is what makes the flow testable and architecture-clean —
    the old version verified the token, checked the audience, and created
    users right here, putting ORM + external-service calls in the mapper
    layer.

    ``auth_token`` is the Google ID token (the ``credential`` the
    frontend receives from Google Identity Services).
    """

    auth_token = serializers.CharField(trim_whitespace=True)
