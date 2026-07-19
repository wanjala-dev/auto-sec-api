from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from django.core.files.base import ContentFile
from django.utils.text import slugify

from components.shared_platform.infrastructure.services.core_utils import generate_password
from components.workspace.application.facades.workspace_facade import ensure_workspace_scaffolding
from components.workspace.application.ports.workspace_bootstrap_port import WorkspaceBootstrapPort
from infrastructure.persistence.project.models import Project
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.uploads.models import File
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import (
    ContributionMeans,
    SubCategory,
    Workspace,
    WorkspaceCategory,
)


class WorkspaceBootstrapRepository(WorkspaceBootstrapPort):
    def ensure_owner(
        self,
        *,
        owner_info: dict[str, Any],
        owner_email_override: str | None = None,
        owner_password_override: str | None = None,
    ) -> CustomUser:
        owner_email = owner_email_override or owner_info["email"]
        owner_password = owner_password_override or owner_info.get("password")
        owner_defaults = {
            "username": owner_email.split("@")[0],
            "first_name": owner_info.get("first_name", ""),
            "last_name": owner_info.get("last_name", ""),
            "is_staff": owner_info.get("is_staff", False),
            "is_active": owner_info.get("is_active", True),
        }

        owner, _ = CustomUser.objects.get_or_create(email=owner_email, defaults=owner_defaults)
        if owner_password:
            owner.set_password(owner_password)
            owner.save()
        UserProfile.objects.get_or_create(user=owner)
        return owner

    def ensure_workspace(
        self,
        *,
        owner: CustomUser,
        workspace_info: dict[str, Any],
        lookup_info: dict[str, Any] | None = None,
    ) -> tuple[Workspace, bool]:
        workspace_photo = workspace_info.get("photo_source_url") or workspace_info.get("photo_url", "")
        workspace = self._lookup_workspace(lookup_info, workspace_info)
        created = False
        if workspace is None:
            workspace, created = Workspace.objects.get_or_create(
                workspace_name=workspace_info["name"],
                defaults={
                    "workspace_owner": owner,
                    "workspace_story": workspace_info.get("story", ""),
                    "status": workspace_info.get("status", "inactive"),
                    "privacy": workspace_info.get("privacy", Workspace.PUBLIC),
                    "is_verified": workspace_info.get("is_verified", False),
                    "photo_url": (workspace_photo[:120] if workspace_photo else ""),
                },
            )
        else:
            workspace.workspace_owner = owner
            workspace.workspace_story = workspace_info.get("story", workspace.workspace_story)
            workspace.status = workspace_info.get("status", workspace.status)
            workspace.privacy = workspace_info.get("privacy", workspace.privacy)
            workspace.is_verified = workspace_info.get("is_verified", workspace.is_verified)
            workspace.workspace_name = workspace_info["name"]
            update_fields = [
                "workspace_owner",
                "workspace_story",
                "status",
                "privacy",
                "is_verified",
                "updated_at",
            ]
            if workspace_photo:
                workspace.photo_url = workspace_photo[:120]
                update_fields.append("photo_url")
            workspace.save(update_fields=update_fields)
        return workspace, created

    def assign_categories(self, *, workspace: Workspace, workspace_info: dict[str, Any]) -> None:
        categories = workspace_info.get("categories", [])
        subcategory_map = workspace_info.get("subcategories", {})
        subcategory_ids = []
        for cat_name in categories:
            category, _ = WorkspaceCategory.objects.get_or_create(name=cat_name)
            workspace.workspace_categories.add(category)
            for sub_name in subcategory_map.get(cat_name, []):
                sub, _ = SubCategory.objects.get_or_create(name=sub_name, category=category)
                subcategory_ids.append(sub.id)
        if subcategory_ids:
            workspace.workspace_subcategories.set(subcategory_ids)

    def assign_contribution_means(self, *, workspace: Workspace, workspace_info: dict[str, Any]) -> None:
        means = workspace_info.get("contribution_means", [])
        if not means:
            return
        matches = ContributionMeans.objects.filter(name__in=means)
        if matches.exists():
            workspace.contribution_means.set(matches)

    def ensure_subscription_plans(self) -> None:
        # Subscription/billing plans are not part of the security product's
        # workspace core. No-op retained to satisfy the bootstrap port contract.
        return None

    def ensure_workspace_scaffolding(
        self,
        *,
        workspace: Workspace,
        owner: CustomUser,
        team_title: str,
    ) -> tuple[Team, Any]:
        return ensure_workspace_scaffolding(workspace, owner, team_title=team_title)

    def ensure_workspace_follower(self, *, workspace: Workspace, user: CustomUser) -> None:
        from components.workspace.application.facades.workspace_facade import ensure_workspace_follower

        ensure_workspace_follower(workspace, user)

    def ensure_staff_team(self, *, workspace: Workspace, owner: CustomUser, title: str) -> Team:
        team, _ = Team.objects.get_or_create(
            workspace=workspace,
            title=title,
            defaults={
                "created_by": owner,
                "status": Team.ACTIVE,
                "privacy": Team.PRIVATE,
            },
        )
        team.members.add(owner)
        return team

    def ensure_contributor_user(
        self,
        *,
        contributor_info: dict[str, Any] | None,
        workspace: Workspace,
        contributors_team: Team,
    ) -> CustomUser:
        contributor_info = contributor_info or {}

        email = contributor_info.get("email")
        if not email:
            workspace_slug = slugify(workspace.workspace_name or str(workspace.id))
            email = f"{workspace_slug}-contributor@example.org"

        defaults = {
            "username": contributor_info.get("username") or email.split("@")[0],
            "first_name": contributor_info.get("first_name", ""),
            "last_name": contributor_info.get("last_name", ""),
            "is_active": contributor_info.get("is_active", True),
        }

        user, created = CustomUser.objects.get_or_create(email=email, defaults=defaults)

        user_dirty = False
        for field in ("first_name", "last_name", "is_active"):
            incoming = defaults[field]
            if getattr(user, field) != incoming:
                setattr(user, field, incoming)
                user_dirty = True

        if not user.is_contributor:
            user.is_contributor = True
            user_dirty = True

        password = contributor_info.get("password")
        if password:
            user.set_password(password)
            user_dirty = True
        elif created:
            user.set_password(generate_password())
            user_dirty = True

        if user_dirty:
            user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile_updates = []
        desired_title = contributor_info.get("title") or profile.title or "Contributor"
        if profile.title != desired_title:
            profile.title = desired_title
            profile_updates.append("title")
        if contributors_team and profile.active_team_id != contributors_team.id:
            profile.active_team_id = contributors_team.id
            profile_updates.append("active_team_id")
        if profile.active_workspace_id != workspace.id:
            profile.active_workspace_id = workspace.id
            profile_updates.append("active_workspace_id")
        if profile_updates:
            profile.save(update_fields=profile_updates)

        if contributors_team:
            contributors_team.members.add(user)

        return user

    def ensure_theme(self, *, workspace: Workspace, theme_spec: dict[str, Any] | None = None) -> Any:
        # Landing-page Theme provisioning was part of the nonprofit CMS surface,
        # which is not part of the security product. No-op retained to satisfy
        # the bootstrap port contract.
        return None

    def finalize_owner_profile(
        self,
        *,
        owner: CustomUser,
        workspace_id: Any,
        active_team_id: Any,
    ) -> None:
        profile, _ = UserProfile.objects.get_or_create(user=owner)
        profile.active_workspace_id = workspace_id
        profile.active_team_id = active_team_id
        profile.save(update_fields=["active_workspace_id", "active_team_id"])

    def seed_projects(
        self,
        *,
        projects: list[dict[str, Any]],
        workspace: Workspace,
        team: Team,
        owner: CustomUser,
    ) -> list[str]:
        added: list[str] = []
        for project in projects:
            obj = Project.objects.filter(workspace=workspace, team=team, title=project["title"]).first()
            if obj:
                if project.get("description") and obj.description != project["description"]:
                    obj.description = project["description"]
                    obj.save(update_fields=["description"])
                continue
            Project.objects.create(
                workspace=workspace,
                team=team,
                title=project["title"],
                description=project.get("description", ""),
                created_by=owner,
            )
            added.append(project["title"])
        return added

    def seed_recipients(
        self,
        *,
        recipients: list[dict[str, Any]],
        workspace: Workspace,
        owner: CustomUser,
        category_config: dict[str, Any] | None,
    ) -> None:
        # Sponsorship recipients are not part of the security product. No-op
        # retained to satisfy the bootstrap port contract.
        return None

    def seed_news(
        self,
        *,
        news_items: list[dict[str, Any]],
        workspace: Workspace,
        owner: CustomUser,
    ) -> None:
        # The workspace News/CMS surface is not part of the security product.
        # No-op retained to satisfy the bootstrap port contract.
        return None

    def seed_pdfs(
        self,
        *,
        pdfs: list[dict[str, Any]],
        workspace: Workspace,
        owner: CustomUser,
        config_dir: Path,
    ) -> list[str]:
        warnings: list[str] = []
        for pdf in pdfs:
            filename = pdf["filename"]
            existing = File.objects.filter(
                file__icontains=filename,
                owner=owner,
                workspace_id=workspace.id,
            ).first()
            if existing:
                continue

            content_bytes = None
            local_path = pdf.get("local_path")
            if local_path:
                file_path = (config_dir / local_path).resolve()
                if file_path.exists() and file_path.is_file():
                    content_bytes = file_path.read_bytes()
                else:
                    warnings.append(f"Missing PDF asset for '{filename}' at {file_path}")
            if content_bytes is None and pdf.get("source_url"):
                try:
                    response = requests.get(pdf["source_url"], timeout=30)
                    response.raise_for_status()
                    content_bytes = response.content
                except Exception as exc:  # pylint: disable=broad-except
                    warnings.append(f"Failed to download '{filename}' from {pdf['source_url']}: {exc}")
            if content_bytes is None:
                placeholder = pdf.get("content", "Sample content for local development only")
                content_bytes = placeholder.encode("utf-8") if isinstance(placeholder, str) else placeholder
            content = ContentFile(content_bytes, name=filename)
            File.objects.create(
                owner=owner,
                workspace_id=str(workspace.id),
                file=content,
                file_type=pdf.get("file_type", "pdf"),
                processing_status="completed",
                pdf_text=pdf.get("description", ""),
                pdf_page_count=pdf.get("page_count", 1),
            )
        return warnings

    def _derive_tenant_identifier(self, raw_value: str | None) -> str | None:
        if not raw_value:
            return None
        candidate = str(raw_value).strip()
        if not candidate:
            return None

        parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
        host = parsed.hostname or candidate.split("/")[0]
        if not host:
            return None
        host = host.split("@")[-1]
        host = host.split(":")[0]

        if host in {"localhost", "127.0.0.1"}:
            return "local"
        if host.endswith(".local"):
            return "local"
        return host

    def _lookup_workspace(
        self,
        lookup_info: dict[str, Any] | None,
        workspace_info: dict[str, Any],
    ) -> Workspace | None:
        lookup_info = lookup_info or {}
        workspace_id = lookup_info.get("id") or lookup_info.get("workspace_id")
        if workspace_id:
            try:
                return Workspace.objects.get(id=workspace_id)
            except Workspace.DoesNotExist:
                return None

        name_hint = lookup_info.get("name") or lookup_info.get("workspace_name")
        if name_hint:
            workspace = Workspace.objects.filter(workspace_name__iexact=name_hint.strip()).first()
            if workspace:
                return workspace

        target_name = workspace_info.get("name")
        if target_name:
            workspace = Workspace.objects.filter(workspace_name__iexact=target_name.strip()).first()
            if workspace:
                return workspace
        return None
