"""Lightweight tests for workspace models and manager helpers."""

import pytest

from infrastructure.persistence.workspaces.models import Workspace, WorkspaceCategory, SubCategory

pytestmark = pytest.mark.django_db


def test_workspace_manager_filters_active(workspace_factory):
    active = workspace_factory(status="active")
    workspace_factory(status="inactive")

    qs = Workspace.objects.all()  # manager filters to active

    assert list(qs) == [active]


def test_workspace_str_uses_name(workspace_factory):
    workspace = workspace_factory(workspace_name="My Workspace")
    assert str(workspace) == "My Workspace"


def test_workspace_category_and_subcategory_str():
    cat = WorkspaceCategory.objects.create(name="Health")
    sub = SubCategory.objects.create(name="Dental", category=cat)

    assert str(cat) == "Health"
    assert str(sub) == "Dental"
