from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

class BroadCast_Email(models.Model):
    subject = models.CharField(max_length=200)
    created = models.DateTimeField(default=timezone.now)
    message  = models.TextField()

    def __unicode__(self):
        return self.subject

    class Meta:
        verbose_name = "BroadCast Email to all Member"
        verbose_name_plural = "BroadCast Email"


class BannerQuerySet(models.QuerySet):
    def active(self):
        now = timezone.now()
        return (
            self.filter(is_active=True)
            .filter(models.Q(starts_at__lte=now) | models.Q(starts_at__isnull=True))
            .filter(models.Q(ends_at__gte=now) | models.Q(ends_at__isnull=True))
            .order_by('priority', '-created_at')
        )


class Banner(models.Model):
    class Scope(models.TextChoices):
        SYSTEM = 'system', _('System')
        WORKSPACE = 'workspace', _('Workspace')
        USER = 'user', _('User')

    class Severity(models.TextChoices):
        INFO = 'info', _('Info')
        WARNING = 'warning', _('Warning')
        ALERT = 'alert', _('Alert')

    title = models.CharField(max_length=160, blank=True)
    message = models.TextField()
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        default=Severity.INFO,
    )
    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        default=Scope.SYSTEM,
    )
    workspace = models.ForeignKey(
        'workspaces.Workspace',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='banners',
    )
    user = models.ForeignKey(
        'users.CustomUser',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='banners',
    )
    is_active = models.BooleanField(default=True)
    dismissible = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BannerQuerySet.as_manager()

    class Meta:
        ordering = ('priority', '-created_at')
        indexes = [
            models.Index(fields=('scope', 'is_active'), name='banner_scope_active_idx'),
            models.Index(fields=('starts_at', 'ends_at'), name='banner_schedule_idx'),
        ]

    def __str__(self):
        scope_target = self.scope
        if self.scope == self.Scope.WORKSPACE and self.workspace_id:
            scope_target = f"{scope_target}:{self.workspace_id}"
        elif self.scope == self.Scope.USER and self.user_id:
            scope_target = f"{scope_target}:{self.user_id}"
        return f"[{self.severity}] {scope_target} {self.title or self.message[:30]}"

    def is_active_now(self):
        now = timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.ends_at and self.ends_at < now:
            return False
        return True
