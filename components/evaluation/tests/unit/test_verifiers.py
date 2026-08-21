"""Both directions, on both verifiers.

A verifier that always fails passes every failure test, so each behaviour here
is pinned from both sides: a case that must PASS beside the case that must
FAIL, and — the third state that matters — the case that must be NOT MEASURED
rather than either. The reason string is asserted too: it is rendered to an
operator working out what their agent did wrong, so "the patch was invalid" is
a defect even when the boolean is right.
"""

from __future__ import annotations

import pytest

from components.evaluation.domain.services.verifiers import (
    Outcome,
    verify_fix_applies,
    verify_no_fabricated_asset,
)

pytestmark = pytest.mark.unit


REPO_FILES = (
    "requirements/base.txt",
    "requirements/dev.txt",
    "src/checkout/client.py",
    "pyproject.toml",
)

GOOD_PATCH = """diff --git a/requirements/base.txt b/requirements/base.txt
--- a/requirements/base.txt
+++ b/requirements/base.txt
@@ -12,7 +12,7 @@
-requests==2.19.1
+requests==2.20.0
"""


class TestFixAppliesPasses:
    def test_a_well_formed_patch_against_a_known_file_passes(self):
        result = verify_fix_applies(GOOD_PATCH, REPO_FILES)

        assert result.outcome is Outcome.PASSED
        assert result.passed is True
        assert result.failed is False
        assert "requirements/base.txt" in result.reason

    def test_a_plain_diff_without_git_ab_prefixes_passes(self):
        patch = (
            "--- requirements/base.txt\n+++ requirements/base.txt\n@@ -1 +1 @@\n-requests==2.19.1\n+requests==2.20.0\n"
        )

        result = verify_fix_applies(patch, REPO_FILES)

        assert result.passed is True

    def test_timestamps_after_the_path_do_not_break_it(self):
        """`diff -u` appends a tab and a timestamp; that is still the same file."""
        patch = (
            "--- requirements/base.txt\t2026-08-20 10:00:00.000000000 +0000\n"
            "+++ requirements/base.txt\t2026-08-20 10:01:00.000000000 +0000\n"
            "@@ -1 +1 @@\n"
            "-requests==2.19.1\n"
            "+requests==2.20.0\n"
        )

        assert verify_fix_applies(patch, REPO_FILES).passed is True

    def test_creating_a_new_file_passes_even_though_it_is_not_in_the_inventory(self):
        """A remediation that ADDS a file is legitimate; requiring the new path
        to already exist would fail every 'add a policy file' fix."""
        patch = "--- /dev/null\n+++ b/src/checkout/security_headers.py\n@@ -0,0 +1,2 @@\n+HSTS = 'max-age=63072000'\n"

        result = verify_fix_applies(patch, REPO_FILES)

        assert result.passed is True, result.reason

    def test_deleting_an_existing_file_passes(self):
        patch = "--- a/pyproject.toml\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-[tool.x]\n-y = 1\n"

        assert verify_fix_applies(patch, REPO_FILES).passed is True

    def test_a_multi_file_patch_over_known_files_passes(self):
        patch = GOOD_PATCH + (
            "--- a/requirements/dev.txt\n+++ b/requirements/dev.txt\n@@ -1 +1 @@\n-pytest==7.0.0\n+pytest==8.0.0\n"
        )

        result = verify_fix_applies(patch, REPO_FILES)

        assert result.passed is True
        assert "requirements/dev.txt" in result.reason


class TestFixAppliesFails:
    def test_a_patch_against_a_file_that_does_not_exist_fails_and_names_it(self):
        patch = GOOD_PATCH.replace("requirements/base.txt", "requirements/production.txt")

        result = verify_fix_applies(patch, REPO_FILES)

        assert result.failed is True
        assert result.passed is False
        assert "requirements/production.txt" in result.reason
        assert result.evidence == ("requirements/production.txt",)

    def test_only_the_unknown_file_of_a_multi_file_patch_is_named(self):
        patch = GOOD_PATCH + (
            "--- a/src/checkout/does_not_exist.py\n+++ b/src/checkout/does_not_exist.py\n@@ -1 +1 @@\n-a\n+b\n"
        )

        result = verify_fix_applies(patch, REPO_FILES)

        assert result.failed is True
        assert result.evidence == ("src/checkout/does_not_exist.py",)
        assert "requirements/base.txt" not in result.reason

    def test_prose_that_is_not_a_diff_fails_and_says_so(self):
        result = verify_fix_applies(
            "You should upgrade requests to 2.20.0 in requirements/base.txt.",
            REPO_FILES,
        )

        assert result.failed is True
        assert "unified diff" in result.reason

    def test_an_empty_patch_fails(self):
        result = verify_fix_applies("   \n\n", REPO_FILES)

        assert result.failed is True
        assert "no patch" in result.reason.casefold()

    def test_file_headers_with_no_hunk_fail(self):
        """A header with no `@@` changes nothing — it is not an applicable patch."""
        result = verify_fix_applies("--- a/requirements/base.txt\n+++ b/requirements/base.txt\n", REPO_FILES)

        assert result.failed is True
        assert "hunk" in result.reason

    def test_a_malformed_hunk_header_fails_and_quotes_it(self):
        patch = "--- a/requirements/base.txt\n+++ b/requirements/base.txt\n@@ bogus @@\n-a\n+b\n"

        result = verify_fix_applies(patch, REPO_FILES)

        assert result.failed is True
        assert "@@ bogus @@" in result.reason


class TestFixAppliesIsTotalAndHonestAboutNotKnowing:
    @pytest.mark.parametrize("garbage", [None, 42, {"patch": "..."}, ["--- a/x"], object()])
    def test_non_text_patch_input_never_raises(self, garbage):
        result = verify_fix_applies(garbage, REPO_FILES)

        assert result.failed is True
        assert result.reason  # a reason, not a bare False

    def test_bytes_are_decoded_rather_than_rejected(self):
        assert verify_fix_applies(GOOD_PATCH.encode(), REPO_FILES).passed is True

    def test_no_inventory_is_not_measured_rather_than_failed(self):
        """We could not check. That is our gap, not the agent's failure."""
        result = verify_fix_applies(GOOD_PATCH, None)

        assert result.outcome is Outcome.NOT_MEASURED
        assert result.passed is False
        assert result.failed is False
        assert result.measured is False

    def test_an_empty_inventory_is_not_measured(self):
        result = verify_fix_applies(GOOD_PATCH, [])

        assert result.outcome is Outcome.NOT_MEASURED
        assert "empty" in result.reason

    def test_a_non_iterable_inventory_is_not_measured_rather_than_raising(self):
        result = verify_fix_applies(GOOD_PATCH, 7)

        assert result.outcome is Outcome.NOT_MEASURED

    def test_the_axis_key_matches_the_vocabulary(self):
        assert verify_fix_applies(GOOD_PATCH, REPO_FILES).axis == "fix_applies"


KNOWN_URNS = (
    "arn:aws:s3:::acme-prod-app-logs",
    "arn:aws:iam::123456789012:role/acme-checkout-task",
    "urn:github:acme/checkout-api",
)


class TestNoFabricatedAssetPasses:
    def test_an_output_citing_only_known_assets_passes(self):
        output = (
            "The role arn:aws:iam::123456789012:role/acme-checkout-task was denied access "
            "to objects in arn:aws:s3:::acme-prod-app-logs."
        )

        result = verify_no_fabricated_asset(output, KNOWN_URNS)

        assert result.outcome is Outcome.PASSED
        assert len(result.evidence) == 2

    def test_an_output_with_no_asset_references_passes(self):
        result = verify_no_fabricated_asset("This is a false positive; it is AWS's documentation key.", KNOWN_URNS)

        assert result.passed is True
        assert "no asset urns" in result.reason.casefold()

    def test_trailing_punctuation_is_not_part_of_the_urn(self):
        result = verify_no_fabricated_asset("Encryption is off on arn:aws:s3:::acme-prod-app-logs.", KNOWN_URNS)

        assert result.passed is True, result.reason

    def test_case_differences_do_not_count_as_fabrication(self):
        result = verify_no_fabricated_asset("See ARN:AWS:S3:::acme-prod-app-logs", KNOWN_URNS)

        assert result.passed is True, result.reason

    def test_an_object_key_under_a_known_bucket_is_not_fabricated(self):
        """Its parent is in the inventory, so the infrastructure is real —
        flagging it would be a false accusation."""
        result = verify_no_fabricated_asset(
            "The exposed object is arn:aws:s3:::acme-prod-app-logs/2026/08/access.log",
            KNOWN_URNS,
        )

        assert result.passed is True, result.reason

    def test_bare_resource_names_are_not_treated_as_references(self):
        """Extraction is deliberately narrow: ordinary English must not be
        mistaken for an invented asset."""
        result = verify_no_fabricated_asset(
            "The acme-prod-analytics bucket and the checkout-api repository look misconfigured.",
            KNOWN_URNS,
        )

        assert result.passed is True
        assert result.evidence == ()

    def test_a_scheme_prefix_with_no_resource_is_ignored(self):
        result = verify_no_fabricated_asset("The urn:aws prefix is used for asset identity.", KNOWN_URNS)

        assert result.passed is True


class TestNoFabricatedAssetFails:
    def test_an_invented_bucket_fails_and_is_named(self):
        output = "Server-side encryption is disabled on arn:aws:s3:::acme-prod-analytics-exports."

        result = verify_no_fabricated_asset(output, KNOWN_URNS)

        assert result.failed is True
        assert result.passed is False
        assert "arn:aws:s3:::acme-prod-analytics-exports" in result.reason
        assert result.evidence == ("arn:aws:s3:::acme-prod-analytics-exports",)

    def test_only_the_invented_asset_is_reported(self):
        output = "arn:aws:s3:::acme-prod-app-logs is fine, but arn:aws:s3:::acme-shadow-bucket is public."

        result = verify_no_fabricated_asset(output, KNOWN_URNS)

        assert result.failed is True
        assert result.evidence == ("arn:aws:s3:::acme-shadow-bucket",)

    def test_a_urn_from_another_workspace_fails(self):
        result = verify_no_fabricated_asset("Patch urn:github:other-corp/payments-api", KNOWN_URNS)

        assert result.failed is True
        assert "other-corp/payments-api" in result.reason

    def test_a_prefix_of_a_known_urn_is_not_treated_as_owned(self):
        """`...:acme-prod-app` is a DIFFERENT bucket from `...:acme-prod-app-logs`;
        substring matching would let a near-miss name pass as real."""
        result = verify_no_fabricated_asset("Check arn:aws:s3:::acme-prod-app", KNOWN_URNS)

        assert result.failed is True


class TestNoFabricatedAssetIsTotalAndHonestAboutNotKnowing:
    def test_no_inventory_is_not_measured_rather_than_failed(self):
        result = verify_no_fabricated_asset("arn:aws:s3:::anything", None)

        assert result.outcome is Outcome.NOT_MEASURED
        assert result.passed is False
        assert result.failed is False

    def test_an_empty_inventory_is_not_measured_and_says_whose_gap_it_is(self):
        result = verify_no_fabricated_asset("arn:aws:s3:::anything", [])

        assert result.outcome is Outcome.NOT_MEASURED
        assert "not the agent" in result.reason.casefold()

    @pytest.mark.parametrize("garbage", [None, 42, {"output": "x"}, object()])
    def test_non_text_output_never_raises(self, garbage):
        result = verify_no_fabricated_asset(garbage, KNOWN_URNS)

        assert result.outcome is Outcome.NOT_MEASURED
        assert result.reason

    def test_bytes_output_is_decoded_rather_than_rejected(self):
        result = verify_no_fabricated_asset(b"arn:aws:s3:::acme-prod-app-logs", KNOWN_URNS)

        assert result.passed is True

    def test_a_single_string_inventory_is_treated_as_one_urn(self):
        """Iterating a bare string character-by-character would produce a
        verdict from nonsense."""
        passing = verify_no_fabricated_asset("arn:aws:s3:::acme-prod-app-logs", "arn:aws:s3:::acme-prod-app-logs")
        failing = verify_no_fabricated_asset("arn:aws:s3:::other", "arn:aws:s3:::acme-prod-app-logs")

        assert passing.passed is True
        assert failing.failed is True

    def test_the_axis_key_matches_the_vocabulary(self):
        assert verify_no_fabricated_asset("", KNOWN_URNS).axis == "no_fabricated_asset"

    def test_as_dict_carries_the_reason_and_the_evidence(self):
        payload = verify_no_fabricated_asset("arn:aws:s3:::acme-ghost", KNOWN_URNS).as_dict()

        assert payload["outcome"] == "failed"
        assert payload["passed"] is False
        assert payload["measured"] is True
        assert payload["evidence"] == ["arn:aws:s3:::acme-ghost"]
        assert payload["reason"]
