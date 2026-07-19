"""Workflow API routes."""

from rest_framework.routers import DefaultRouter
from django.urls import path

from components.workflow.api.controller import (
    WorkflowBindingViewSet,
    WorkflowRunViewSet,
    WorkflowTemplateViewSet,
    WorkflowTriggerList,
    WorkflowViewSet,
)

router = DefaultRouter()
router.register(r"workflow-templates", WorkflowTemplateViewSet, basename="workflow-template")
router.register(r"workflows", WorkflowViewSet, basename="workflow")
router.register(r"workflow-bindings", WorkflowBindingViewSet, basename="workflow-binding")
router.register(r"workflow-runs", WorkflowRunViewSet, basename="workflow-run")

urlpatterns = [
    path("workflow-triggers/", WorkflowTriggerList.as_view(), name="workflow-triggers"),
]

urlpatterns += router.urls
