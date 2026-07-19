import os


def test_template_dirs_are_absolute_paths(settings):
    template_dirs = settings.TEMPLATES[0]["DIRS"]

    assert template_dirs
    assert all(os.path.isabs(path) for path in template_dirs)
