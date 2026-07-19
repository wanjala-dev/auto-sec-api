from django.conf import settings
from django.db import models
from django.utils import timezone

#
# Import models
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import ContributionMeans, Workspace

#
# Models


class Priority(models.TextChoices):
    NO_PRIORITY = "NP", "No priority"
    URGENT = "UR", "Urgent"
    HIGH = "HI", "High"
    MEDIUM = "MD", "Medium"
    LOW = "LO", "Low"


class Status(models.TextChoices):
    BACKLOG = "BL", "Backlog"
    THINK = "TH", "Think"
    PROTOTYPE = "PR", "Prototype"
    BUILD = "BU", "Build"
    RELEASE = "RE", "Release"
    TWEAK = "TW", "Tweak"
    COMPLETED = "CO", "Completed"
    CANCELED = "CA", "Canceled"


class Tag(models.Model):
    name = models.CharField(max_length=1000, unique=True)

    def __str__(self):
        return self.name


class ProjectMilestone(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    target_date = models.DateField()
    creator = models.ForeignKey(
        CustomUser, related_name="created_milestones", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.created_at:
            self.created_at = timezone.now()
        super().save(*args, **kwargs)


class ProjectUpdate(models.Model):
    PUBLIC = "public"
    PRIVATE = "private"

    PRIVACY_CHOICES = (
        (PUBLIC, "public"),
        (PRIVATE, "private"),
    )

    Update = models.TextField()
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    Project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="project_updates")
    created_on = models.DateTimeField(default=timezone.now)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="project_update_author", on_delete=models.CASCADE)
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="project_update_likes")
    privacy = models.CharField(
        max_length=8,
        choices=PRIVACY_CHOICES,
        default=PUBLIC,
    )
    dislikes = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="project_update_dislikes")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, blank=True, null=True, related_name="+")
    tags = models.ManyToManyField("Tag", blank=True)

    def create_tags(self):
        for word in self.Update.split():
            if word[0] == "#":
                tag = Tag.objects.get(name=word[1:])
                if tag:
                    self.tags.add(tag.pk)
                else:
                    tag = Tag(name=word[1:])
                    tag.save()
                    self.tags.add(tag.pk)
            self.save()

    @property
    def recipients(self):
        return ProjectUpdate.objects.filter(parent=self).order_by("-created_on").all()

    @property
    def is_parent(self):
        if self.parent is None:
            return True
        return False

    def __str__(self):
        return self.Update


class Project(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, related_name="projects", on_delete=models.CASCADE)
    # donation_form FK dropped in the auto-sec fork (donation_forms removed).
    title = models.CharField(max_length=255)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(CustomUser, related_name="projects", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    lead = models.ForeignKey(
        CustomUser, related_name="leading_projects", on_delete=models.SET_NULL, null=True, blank=True
    )
    priority = models.CharField(
        max_length=2,
        choices=Priority.choices,
        default=Priority.NO_PRIORITY,
    )
    status = models.CharField(
        max_length=2,
        choices=Status.choices,
        default=Status.BACKLOG,
    )
    resources = models.TextField(blank=True, null=True)  # Added resources
    description = models.TextField(blank=True, null=True)  # Added description
    milestones = models.ManyToManyField(ProjectMilestone, blank=True, related_name="projects")
    bgColor = models.CharField(max_length=20, blank=True, null=True)  # Added bgColor
    # Public fundraising ask for donor-facing progress bars (donation-form
    # project designations). Deliberately independent of the internal budget;
    # null = no goal set → no progress bar is rendered.
    public_goal_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    contribution_means = models.ManyToManyField(ContributionMeans, blank=True, related_name="projects")

    # Optional column placement for project-level Kanban boards
    board_column = models.ForeignKey(
        "Column",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="board_projects",
    )

    # Soft-delete flag — a trashed project drops off the board but stays
    # restorable from the recycle bin (ProjectSoftDeleteAdapter), mirroring
    # every other trashable entity (recipient, budget, transaction, …).
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def registered_time(self):
        return sum(entry.minutes for entry in self.entries.all())

    def num_tasks_todo(self):
        return self.tasks.filter(status=Task.TODO).count()


class Column(models.Model):
    project = models.ForeignKey(Project, related_name="columns", on_delete=models.CASCADE, null=True)
    title = models.CharField(max_length=255)
    order = models.IntegerField(default=0)
    hidden = models.BooleanField(default=False)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, related_name="columns", on_delete=models.SET_NULL, null=True)
    color = models.CharField(max_length=7, default="#FFFFFF")
    is_archived = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, related_name="columns", on_delete=models.CASCADE)

    class Meta:
        ordering = ["order"]
        constraints = [
            # A team's board (project-less columns) cannot have two columns with
            # the same title. Makes ``get_or_create`` for the Triage column
            # atomic under concurrent triage runs — the loser hits this
            # constraint and re-reads instead of creating a duplicate.
            models.UniqueConstraint(
                fields=["team", "workspace", "title"],
                condition=models.Q(project__isnull=True),
                name="uniq_board_column_title_per_team",
            )
        ]

    def __str__(self):
        return self.title


class Task(models.Model):
    #
    # Status choices

    TODO = "todo"
    DONE = "done"
    ARCHIVED = "archived"

    CHOICES_STATUS = ((TODO, "Todo"), (DONE, "Done"), (ARCHIVED, "Archived"))

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, related_name="tasks", on_delete=models.CASCADE)
    project = models.ForeignKey(Project, related_name="tasks", on_delete=models.CASCADE, null=True, blank=True)
    # event / campaign / recipient FKs dropped in the auto-sec fork
    # (events, campaign, sponsorship-recipients contexts removed).
    grant = models.ForeignKey(
        "workspaces.Grant",
        related_name="tasks",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    column = models.ForeignKey(Column, related_name="tasks", on_delete=models.SET_NULL, null=True)
    title = models.CharField(max_length=255)
    assigned_to = models.ManyToManyField(CustomUser, related_name="assigned_tasks", blank=True)
    created_by = models.ForeignKey(CustomUser, related_name="tasks", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=CHOICES_STATUS, default=TODO)
    order = models.PositiveIntegerField(default=0)
    contribution_means = models.ManyToManyField(ContributionMeans, blank=True, related_name="tasks")
    due_date = models.DateTimeField(null=True, blank=True)
    requires_review = models.BooleanField(default=False)
    priority = models.CharField(max_length=12, choices=Priority.choices, default=Priority.MEDIUM)
    # Provenance label for the upstream system that produced this task.
    # AI-finding tasks carry ``ai.<detector_or_action_key>`` (e.g.
    # ``ai.book_balance.budget_overrun`` or ``ai.budget_variance_detected``).
    # Empty for human-created tasks. Phase 4 of the Agents-as-Teammates
    # migration (``docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md``)
    # introduced this field so the workflow engine can route AI tasks
    # without joining through ``AIAction``.
    source_type = models.CharField(max_length=64, blank=True, default="", db_index=True)
    # Free-form narrative for the task. Specialist-agent tasks land the
    # detector's human-readable summary here; manual tasks may use it
    # for an optional description. Phase 5 of the Agents-as-Teammates
    # migration moved this off the deleted ``AIAction.summary`` field.
    description = models.TextField(blank=True, default="")
    # Structured payload carried alongside the task. For AI-finding
    # tasks this stores agent attribution + the detector context that
    # used to live on ``AIAction.payload`` / ``AIAction.context``
    # (e.g. ``{"agent_type": "budget_specialist", "impact_score": 80,
    # "payload": {...}, "context": {...}}``). Empty for manual tasks.
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def registered_time(self):
        return sum(entry.minutes for entry in self.entries.all())


class TaskComment(models.Model):
    comment = models.TextField()
    created_on = models.DateTimeField(default=timezone.now)
    author = models.ForeignKey(CustomUser, related_name="task_comments", on_delete=models.CASCADE)
    task = models.ForeignKey("Task", related_name="comments", on_delete=models.CASCADE)
    likes = models.ManyToManyField(CustomUser, blank=True, related_name="task_comment_likes")
    dislikes = models.ManyToManyField(CustomUser, blank=True, related_name="task_comment_dislikes")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, blank=True, null=True, related_name="replies")
    tags = models.ManyToManyField("Tag", blank=True)

    class Meta:
        ordering = ["-created_on"]

    def __str__(self):
        preview = self.comment[:30].strip()
        return preview or f"Comment {self.pk}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.create_tags()

    def create_tags(self):
        """Attach hashtag-derived Tag objects to the comment."""
        for word in self.comment.split():
            if word.startswith("#") and len(word) > 1:
                tag_name = word[1:]
                tag, _ = Tag.objects.get_or_create(name=tag_name)
                self.tags.add(tag.pk)

    @property
    def recipients(self):
        return self.replies.order_by("-created_on").all()

    @property
    def is_parent(self):
        return self.parent is None


class ProjectEntry(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, related_name="entries", on_delete=models.CASCADE)
    project = models.ForeignKey(Project, related_name="entries", on_delete=models.CASCADE, blank=True, null=True)
    task = models.ForeignKey(Task, related_name="entries", on_delete=models.CASCADE, blank=True, null=True)
    minutes = models.IntegerField(default=0)
    is_tracked = models.BooleanField(default=False)
    created_by = models.ForeignKey(CustomUser, related_name="project_entries", on_delete=models.CASCADE)
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        if self.task:
            return "%s - %s" % (self.task.title, self.created_at)

        return "%s" % self.created_at
