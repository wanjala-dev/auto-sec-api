"""URL routing for the audit context API."""

from django.urls import path

from components.audit.api.controller import AuditLogListView

urlpatterns = [
    path("entries/", AuditLogListView.as_view(), name="audit-entries"),
]
