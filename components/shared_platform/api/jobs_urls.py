"""Routes for the generic background-jobs read API. Mounted at ``/jobs/``."""

from django.urls import path

from components.shared_platform.api.jobs_controller import ActiveJobsView, JobDetailView

jobs_urlpatterns = [
    path("workspaces/<uuid:workspace_id>/active/", ActiveJobsView.as_view(), name=ActiveJobsView.name),
    path("workspaces/<uuid:workspace_id>/<uuid:job_id>/", JobDetailView.as_view(), name=JobDetailView.name),
]
