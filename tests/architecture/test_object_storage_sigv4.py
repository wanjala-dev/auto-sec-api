"""Architecture guardrail: no object-storage client is ever built without SigV4.

## Why this test exists

botocore's default for a client built with an explicit ``endpoint_url`` is a legacy
**SigV2** presigned URL. SigV2 folds ``Content-Type`` into the signed string; SigV4
signs only ``host``. So a SigV2 presigned PUT is rejected the moment the uploading
client sends a ``Content-Type`` header — measured live against our own MinIO
(``RELEASE.2025-09-07T16-13-09Z``): SigV2 PUT + ``Content-Type`` → **403
SignatureDoesNotMatch**, the identical SigV4 PUT → 200. Separately, AWS regions
launched after January 2014 reject SigV2 entirely.

This defect is invisible to the test suite. A presigned URL is signed material handed
to a *third party*; it fails in that client, against a real object store, long after
our process returned success. #311 shipped the scan-artifact channel fully green and
every upload failed in production.

It had already happened three times independently — scan artifacts, SBOM download,
report download — because each call site was written by mirroring the previous one,
and the previous one was wrong. Mirroring is how this bug class propagates, so the
durable fix is not "add SigV4 in three more places", it is to make a
wrongly-configured client unbuildable and assert that here.

## The rule

Construct S3 clients through
``infrastructure.storage.object_storage.build_object_storage_client``, which always
sets ``signature_version="s3v4"``.

A direct ``boto3.client("s3", ...)`` is allowed **only** if that same call explicitly
passes a ``Config(signature_version="s3v4")``. That escape hatch exists so a genuinely
special case is possible, but it must be visible in the diff rather than inherited by
accident.

## Deliberately out of scope

``components/integrations/infrastructure/adapters/log_sources/_aws_creds.py`` builds a
client for a *variable* service (``s3`` or ``logs``) from a customer's assume-role
credentials. It is not an object-storage factory and never presigns, so it is not
matched here — this test keys off the literal service name ``"s3"``, which is exactly
the set of clients that can mint a presigned URL.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.arch

ROOT = Path(__file__).resolve().parents[2]

# Where the one correct client factory lives. If this moves, this test must move with it.
FACTORY_MODULE = ROOT / "infrastructure" / "storage" / "object_storage.py"
FACTORY_FUNCTION = "build_object_storage_client"
REQUIRED_SIGNATURE_VERSION = "s3v4"

# Only real source is scanned. Tests legitimately build stub/fake clients, and vendored
# code is not ours to fix.
SCANNED_DIRS = ("components", "infrastructure", "api")
SKIP_PARTS = {"migrations", "tests", "test", "node_modules", ".venv", "site-packages"}


def _python_files():
    for directory in SCANNED_DIRS:
        for path in (ROOT / directory).rglob("*.py"):
            if SKIP_PARTS & set(path.parts):
                continue
            yield path


def _is_s3_client_call(node: ast.Call) -> bool:
    """True for ``boto3.client("s3", ...)`` / ``client("s3", ...)`` — literal service only."""
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name != "client":
        return False
    # Positional form: boto3.client("s3", ...)
    if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "s3":
        return True
    # Keyword form: boto3.client(service_name="s3", ...)
    return any(
        kw.arg == "service_name" and isinstance(kw.value, ast.Constant) and kw.value.value == "s3"
        for kw in node.keywords
    )


def _declares_sigv4(node: ast.Call) -> bool:
    """True when this very call passes ``config=Config(signature_version="s3v4")``."""
    for keyword in node.keywords:
        if keyword.arg != "config" or not isinstance(keyword.value, ast.Call):
            continue
        for config_kw in keyword.value.keywords:
            if (
                config_kw.arg == "signature_version"
                and isinstance(config_kw.value, ast.Constant)
                and config_kw.value.value == REQUIRED_SIGNATURE_VERSION
            ):
                return True
    return False


def test_the_canonical_factory_exists_and_pins_sigv4():
    """The factory is the whole mechanism — assert it is real and correct.

    Without this, every other assertion below could pass against a factory that had
    quietly stopped setting SigV4, which is precisely the silent drift being guarded.
    """
    assert FACTORY_MODULE.exists(), f"The canonical object-storage factory is missing: {FACTORY_MODULE}"
    tree = ast.parse(FACTORY_MODULE.read_text(encoding="utf-8"))

    factory = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == FACTORY_FUNCTION),
        None,
    )
    assert factory is not None, f"{FACTORY_MODULE} must define {FACTORY_FUNCTION}()"

    signs_v4 = any(
        isinstance(n, ast.Constant) and n.value == REQUIRED_SIGNATURE_VERSION for n in ast.walk(factory)
    ) or any(isinstance(n, ast.Constant) and n.value == REQUIRED_SIGNATURE_VERSION for n in ast.walk(tree))
    assert signs_v4, (
        f"{FACTORY_FUNCTION}() no longer pins signature_version={REQUIRED_SIGNATURE_VERSION!r}. "
        "Every presigned URL in the product depends on it; see this module's docstring."
    )


def test_no_s3_client_is_built_without_sigv4():
    """Every S3 client goes through the factory, or declares SigV4 inline."""
    offenders = []
    for path in _python_files():
        if path == FACTORY_MODULE:
            continue  # the factory is where the one legitimate raw construction lives
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file is another test's failure
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_s3_client_call(node) and not _declares_sigv4(node):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert not offenders, (
        "S3 client(s) constructed without SigV4:\n  "
        + "\n  ".join(offenders)
        + f"\n\nUse infrastructure.storage.object_storage.{FACTORY_FUNCTION}() instead.\n"
        "botocore defaults these to legacy SigV2 presigned URLs, which 403 as soon as the "
        "client sends a Content-Type header and are rejected outright by AWS regions newer "
        "than 2014. Unit tests CANNOT catch this — the failure happens in the third party "
        "holding the URL. See this module's docstring for the measured evidence."
    )
