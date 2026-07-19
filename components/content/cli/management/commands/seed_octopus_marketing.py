"""Seed the Octopus marketing teamspace + dogfood blog posts.

Idempotently provisions, on our OWN system (app.octopusintl.org):

  1. the owner user ``octopus.ai.intl@gmail.com``
  2. an ``Octopus`` TEAMSPACE owned by that user
  3. a few PUBLISHED ``WritingDraft`` blogs (``kind='blog'``) authored in it

Those blogs surface on the marketing landing (www.octopusintl.org) via the
public blog API (``/content/<workspace_id>/blogs/``) — i.e. we dogfood our own
Content/Writing product to power the marketing blog.

Safe to re-run. Prints the workspace_id (needed to wire the landing) and, when
the owner is newly created, the generated password.

    docker exec compose-web-1 python manage.py seed_octopus_marketing
    docker exec compose-web-1 python manage.py seed_octopus_marketing --password '<pw>'
"""

from __future__ import annotations

import logging
import secrets

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)

OWNER_EMAIL = "octopus.ai.intl@gmail.com"
OWNER_USERNAME = "octopus-ai-intl"
WORKSPACE_NAME = "Octopus"

# Real, on-voice marketing posts (honest, no banned claims). body_html is the
# canonical content field on WritingDraft — no separate markdown/body field.
BLOGS: list[dict[str, str]] = [
    {
        "title": "Your quarterly funder report, in an hour — not two weeks",
        "body_html": (
            "<p>Most small nonprofits dread the quarterly report. The money moved "
            "months ago, the receipts are scattered across inboxes and shoeboxes, and "
            "someone has to reconcile it all into something a funder will trust.</p>"
            "<p>It doesn't have to be that way. When every gift, expense, and receipt "
            "lives in one set of books as it happens, the report is mostly written by "
            "the time you sit down to write it. You review, you add the story, you "
            "send.</p>"
            "<p>That's the whole idea behind Octopus: your team runs the work on one "
            "ledger, and the report is generated from that same ledger — categorised, "
            "receipted, and ready for a human to check before it goes anywhere.</p>"
        ),
    },
    {
        "title": "Donors don't leave because they stop caring — they leave because they stop hearing",
        "body_html": (
            "<p>Only about four in ten donors ever give to the same organisation a "
            "second time. It's tempting to read that as fickleness. It usually isn't.</p>"
            "<p>People give because they want to change something. When they never hear "
            "what changed, the gift starts to feel like it disappeared. Silence, not "
            "disinterest, is what ends most giving relationships.</p>"
            "<p>The fix isn't a slicker appeal — it's a window into the work itself. "
            "Show a supporter where their gift went, what it bought, and for whom, and "
            "you replace a leap of faith with something they can see. That's the "
            "relationship worth building.</p>"
        ),
    },
    {
        "title": "From first gift to monthly sponsor: designing a giving flow donors trust",
        "body_html": (
            "<p>A first gift is a question: <em>can I trust you with this?</em> A "
            "monthly commitment is the answer. The distance between the two is built "
            "out of small, honest moments — not clever asks.</p>"
            "<p>Make it easy to give, and easy to see what happened next. Confirm the "
            "gift plainly. Follow up with something real — a receipt, an update, the "
            "name of the programme it supported. Let the supporter choose to keep "
            "going, rather than trapping them in a subscription they can't inspect.</p>"
            "<p>Transparency isn't a marketing tactic here; it's the mechanism. When a "
            "donor can watch their gift do its work, becoming a monthly sponsor stops "
            "feeling like a risk and starts feeling like a relationship.</p>"
        ),
    },
]


class Command(BaseCommand):
    help = "Seed the Octopus marketing teamspace + dogfood blog posts (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-id",
            default=None,
            help="Seed blogs into an EXISTING workspace (its owner becomes the author). "
            "When omitted, the Octopus teamspace + owner are created.",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Owner password (a strong one is generated if omitted). Ignored with --workspace-id.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing.",
        )

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no writes."))
            self.stdout.write(f"Would ensure user {OWNER_EMAIL}, teamspace '{WORKSPACE_NAME}', {len(BLOGS)} blogs.")
            return
        with transaction.atomic():
            self._run(opts.get("password"), opts.get("workspace_id"))

    def _run(self, password: str | None, workspace_id: str | None) -> None:
        from infrastructure.persistence.content.models import WritingDraft
        from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

        # Mode A: seed into an EXISTING workspace (e.g. one created in the app UI).
        if workspace_id:
            workspace = Workspace.objects.all_objects().filter(id=workspace_id).first()
            if workspace is None:
                raise CommandError(f"Workspace {workspace_id} not found.")
            author = workspace.workspace_owner
            if author is None:
                raise CommandError(f"Workspace {workspace_id} has no owner to author blogs as.")
            self._log("teamspace", False, f"{workspace.workspace_name} ({workspace.id})")
            self._seed_blogs(WritingDraft, workspace, author)
            self._report(workspace, None)
            return

        # Mode B: create the Octopus teamspace + owner from scratch.
        CustomUser = django_apps.get_model("users", "CustomUser")
        UserProfile = django_apps.get_model("users", "UserProfile")
        Sector = django_apps.get_model("sectors", "Sector")

        # 1. Owner user
        user = CustomUser.objects.filter(email=OWNER_EMAIL).first()
        generated_password = None
        if user is None:
            generated_password = password or ("Oct-" + secrets.token_urlsafe(16))
            user = CustomUser.objects.create_user(
                username=OWNER_USERNAME,
                email=OWNER_EMAIL,
                password=generated_password,
            )
            user.first_name = "Octopus"
            user.last_name = "Marketing"
            user.is_verified = True
            user.is_onboard_complete = True
            user.save(update_fields=["first_name", "last_name", "is_verified", "is_onboard_complete"])
            self._log("user", True, OWNER_EMAIL)
        else:
            self._log("user", False, OWNER_EMAIL)
        profile, _ = UserProfile.objects.get_or_create(user=user)

        # 2. Octopus teamspace + owner membership
        sector, _ = Sector.objects.get_or_create(slug="nonprofit", defaults={"name": "Nonprofit"})
        workspace = (
            Workspace.objects.all_objects()
            .filter(workspace_owner=user, workspace_name=WORKSPACE_NAME, workspace_type=Workspace.TEAMSPACE)
            .first()
        )
        if workspace is None:
            workspace = Workspace.objects.create(
                workspace_owner=user,
                workspace_name=WORKSPACE_NAME,
                workspace_type=Workspace.TEAMSPACE,
                sector=sector,
                status="active",
                privacy=Workspace.PUBLIC,
            )
            self._log("teamspace", True, str(workspace.id))
        else:
            self._log("teamspace", False, str(workspace.id))

        WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=user,
            is_impersonation=False,
            defaults={
                "role": WorkspaceMembership.Role.OWNER,
                "persona": WorkspaceMembership.Persona.ADMIN,
                "status": WorkspaceMembership.Status.ACTIVE,
            },
        )
        if not profile.active_workspace_id:
            profile.active_workspace_id = workspace.id
            profile.save(update_fields=["active_workspace_id"])

        # 3. Published blog posts
        self._seed_blogs(WritingDraft, workspace, user)
        self._report(workspace, generated_password)

    def _seed_blogs(self, WritingDraft, workspace, author) -> None:
        for post in BLOGS:
            _, created = WritingDraft.objects.get_or_create(
                workspace=workspace,
                title=post["title"],
                kind="blog",
                defaults={
                    "author": author,
                    "body_html": post["body_html"],
                    "status": "published",
                    "ai_drafted": False,
                },
            )
            self._log("blog", created, post["title"][:48])

    def _report(self, workspace, generated_password: str | None) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Octopus marketing blogs seeded."))
        self.stdout.write(f"  workspace_id : {workspace.id}")
        self.stdout.write(
            f"  owner        : {workspace.workspace_owner.email if workspace.workspace_owner else '?'}"
        )
        self.stdout.write(f"  public blogs : /content/public/{workspace.id}/blogs/")
        if generated_password:
            self.stdout.write(self.style.WARNING(f"  owner password (save it): {generated_password}"))

    def _log(self, label: str, created: bool, detail: str) -> None:
        verb = self.style.SUCCESS("created") if created else "exists "
        self.stdout.write(f"  [{verb}] {label}: {detail}")
