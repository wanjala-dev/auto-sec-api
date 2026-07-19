from django.db import models

from infrastructure.persistence.users.models import CustomUser

FINANCIAL_REPORT_FREQUENCY_KEY = "financial_report_frequency"
FINANCIAL_REPORT_FREQUENCY_DAILY = "daily"
FINANCIAL_REPORT_FREQUENCY_WEEKLY = "weekly"
FINANCIAL_REPORT_FREQUENCY_MONTHLY = "monthly"
FINANCIAL_REPORT_FREQUENCY_ANNUALLY = "annually"
FINANCIAL_REPORT_FREQUENCY_CHOICES = (
    (FINANCIAL_REPORT_FREQUENCY_DAILY, "Daily"),
    (FINANCIAL_REPORT_FREQUENCY_WEEKLY, "Weekly"),
    (FINANCIAL_REPORT_FREQUENCY_MONTHLY, "Monthly"),
    (FINANCIAL_REPORT_FREQUENCY_ANNUALLY, "Annually"),
)
FINANCIAL_REPORT_FREQUENCY_VALUES = {
    FINANCIAL_REPORT_FREQUENCY_DAILY,
    FINANCIAL_REPORT_FREQUENCY_WEEKLY,
    FINANCIAL_REPORT_FREQUENCY_MONTHLY,
    FINANCIAL_REPORT_FREQUENCY_ANNUALLY,
}
FINANCIAL_REPORT_FREQUENCY_DEFAULT = FINANCIAL_REPORT_FREQUENCY_MONTHLY
FINANCIAL_REPORT_FREQUENCY_ALIASES = {
    "annual": FINANCIAL_REPORT_FREQUENCY_ANNUALLY,
    "yearly": FINANCIAL_REPORT_FREQUENCY_ANNUALLY,
    "year": FINANCIAL_REPORT_FREQUENCY_ANNUALLY,
}

FINANCIAL_REPORT_INTERVAL_UNIT_KEY = "financial_report_interval_unit"
FINANCIAL_REPORT_INTERVAL_VALUE_KEY = "financial_report_interval_value"
FINANCIAL_REPORT_INTERVAL_UNIT_CHOICES = (
    ("day", "Day"),
    ("week", "Week"),
    ("month", "Month"),
    ("year", "Year"),
)
FINANCIAL_REPORT_INTERVAL_UNIT_VALUES = {
    "day",
    "week",
    "month",
    "year",
}
FINANCIAL_REPORT_INTERVAL_UNIT_ALIASES = {
    "days": "day",
    "weeks": "week",
    "months": "month",
    "years": "year",
    "annually": "year",
    "yearly": "year",
}


# Org-wide login-activity / audit-log VISIBILITY toggle (identity context reads
# it through OrgAuditLogSettingsPort). Default ON — turning it off hides the
# org admin surfaces (/identity/workspaces/<id>/login-activity|sessions) but
# NEVER stops auth-event collection.
AUDIT_LOG_ENABLED_KEY = "audit_log_enabled"
AUDIT_LOG_ENABLED_DEFAULT = True


def default_workspace_notification_settings():
    return {
        "donations": False,
        "expenses": False,
        "income": False,
        "story": True,
        "sources": False,
        "team": False,
        "budget": False,
        "activities": False,
        "gallery": False,
        "comments": False,
        "farming": False,
        "sponsorship": False,
        "payroll": False,
        "fundraising": False,
        "books_records": False,
    }


def default_workspace_preference_settings():
    """Return merged defaults for workspace notification and report settings."""
    settings = default_workspace_notification_settings()
    settings[FINANCIAL_REPORT_FREQUENCY_KEY] = FINANCIAL_REPORT_FREQUENCY_DEFAULT
    settings[AUDIT_LOG_ENABLED_KEY] = AUDIT_LOG_ENABLED_DEFAULT
    return settings


WORKSPACE_NOTIFICATION_DEFAULTS = default_workspace_notification_settings()


class UserPreference(models.Model):
    LIGHT = "Light"
    DARK = "Dark"
    DARKMODE_CHOICES = (
        (LIGHT, "Light"),
        (DARK, "Dark"),
    )
    UI_VERSION_V1 = "v1"
    UI_VERSION_V2 = "v2"
    UI_VERSION_CHOICES = (
        (UI_VERSION_V1, "V1 Classic"),
        (UI_VERSION_V2, "V2 Command Center"),
    )
    user = models.OneToOneField(to=CustomUser, on_delete=models.CASCADE)
    darkmode = models.CharField(
        max_length=20,
        choices=DARKMODE_CHOICES,
        default=DARK,
    )
    language = models.CharField(max_length=250, blank=True)
    email_notifications = models.BooleanField(default=False)
    push_notifications = models.BooleanField(default=False)
    notifications_enabled = models.BooleanField(default=True)
    ui_version = models.CharField(
        max_length=10,
        choices=UI_VERSION_CHOICES,
        default=UI_VERSION_V1,
        help_text="Which UI variant the user prefers (v1=classic, v2=command center).",
    )
    # Personalized recommendations are OPT-IN for every donor (Quebec Law 25
    # s.8.1 requires profiling off-by-default; adopted globally). When False
    # (the default), the donor gets the need-based + popularity default slate
    # and NO behavioural profile is built or used. Read by the recommendations
    # context via PersonalizationConsentPort. See recommendations design §8.3.
    recommendations_personalized = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user}'s preferences"


class WorkspacePreference(models.Model):
    """Per-workspace notification and financial report preferences."""

    workspace = models.OneToOneField(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="notification_preference",
    )
    settings = models.JSONField(default=default_workspace_notification_settings, blank=True)

    def __str__(self):
        return f"{self.workspace}'s preferences"

    @classmethod
    def default_settings(cls):
        return default_workspace_preference_settings()

    def get_settings(self):
        merged = self.default_settings()
        merged.update(self.settings or {})
        return merged

    def update_settings(self, updates: dict, *, commit: bool = True):
        """Update workspace settings while preserving types for known keys."""
        clean_updates = {}
        for key, value in (updates or {}).items():
            if key in WORKSPACE_NOTIFICATION_DEFAULTS:
                clean_updates[key] = bool(value)
                continue
            if key == AUDIT_LOG_ENABLED_KEY:
                clean_updates[key] = bool(value)
                continue
            if key == FINANCIAL_REPORT_FREQUENCY_KEY:
                if not value:
                    continue
                normalized = str(value).strip().lower()
                normalized = FINANCIAL_REPORT_FREQUENCY_ALIASES.get(normalized, normalized)
                if normalized in FINANCIAL_REPORT_FREQUENCY_VALUES:
                    clean_updates[key] = normalized
                continue
            if key == FINANCIAL_REPORT_INTERVAL_UNIT_KEY:
                if not value:
                    continue
                normalized = str(value).strip().lower()
                normalized = FINANCIAL_REPORT_INTERVAL_UNIT_ALIASES.get(normalized, normalized)
                if normalized in FINANCIAL_REPORT_INTERVAL_UNIT_VALUES:
                    clean_updates[key] = normalized
                continue
            if key == FINANCIAL_REPORT_INTERVAL_VALUE_KEY:
                if value is None or value == "":
                    continue
                try:
                    numeric_value = int(value)
                except (TypeError, ValueError):
                    continue
                if numeric_value > 0:
                    clean_updates[key] = numeric_value
                continue
            clean_updates[key] = value
        data = self.settings or {}
        data.update(clean_updates)
        self.settings = data
        if commit:
            self.save(update_fields=["settings"])
        return self
