import importlib


def test_social_models_importable():
    importlib.import_module("social.models")
