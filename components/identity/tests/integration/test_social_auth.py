import importlib


def test_social_auth_models_importable():
    importlib.import_module("social_auth.models")
