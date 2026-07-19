from django.db import models
from django.utils.translation import gettext_lazy as _


class HoneypotAttempt(models.Model):
    """
    Stores metadata for unsolicited admin login attempts so we can review and alert on them.
    """

    attempted_at = models.DateTimeField(auto_now_add=True)
    username = models.CharField(max_length=150, blank=True)
    password = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    path = models.CharField(max_length=255, blank=True)
    method = models.CharField(max_length=10, blank=True)
    referer = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("-attempted_at",)
        verbose_name = _("admin honeypot attempt")
        verbose_name_plural = _("admin honeypot attempts")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.username or 'unknown'}@{self.ip_address or 'n/a'} ({self.attempted_at:%Y-%m-%d %H:%M:%S})"
