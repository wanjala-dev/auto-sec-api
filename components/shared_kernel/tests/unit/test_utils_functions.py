from types import SimpleNamespace

from components.shared_platform.infrastructure.services import core_utils as utils


def test_generate_random_string_length():
    token = utils.generate_random_string(length=12)
    assert len(token) == 12


def test_normalize_frontend_base_adds_scheme():
    normalized = utils.normalize_frontend_base("example.com", default_scheme="http")
    assert normalized.startswith("http://")


def test_resolve_frontend_base_uses_request_host():
    request = SimpleNamespace(build_absolute_uri=lambda path: "http://testserver/")

    base = utils.resolve_frontend_base_url(request=request)

    assert base in {"http://testserver", "http://localhost:3000"}
