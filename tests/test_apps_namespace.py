import importlib


def test_apps_namespace_aliases_root_modules():
    for module in ("workspaces", "budget", "users"):
        alias = importlib.import_module(f"infrastructure.persistence.{module}")
        real = importlib.import_module(module)
        assert alias.__file__ == real.__file__


def test_apps_namespace_aliases_submodules():
    agg_alias = importlib.import_module("infrastructure.persistence.workspaces.aggregations")
    agg = importlib.import_module("workspaces.aggregations")
    assert agg_alias.__file__ == agg.__file__


def test_workspaces_app_config_registered_under_alias(settings):
    from django.apps import apps

    config = apps.get_app_config("workspaces")
    workspace_module = importlib.import_module("infrastructure.persistence.workspaces")
    assert getattr(config.module, "__file__", None) == getattr(workspace_module, "__file__", None)
    assert config.name == "infrastructure.persistence.workspaces"
