"""Unit tests for the (heuristic) exposure classifier."""

from __future__ import annotations

import pytest

from components.cloud_graph.domain.services.exposure_classifier import classify_exposure
from components.cloud_graph.domain.value_objects.enums import Exposure

pytestmark = [pytest.mark.unit]


class TestClassifyExposure:
    @pytest.mark.parametrize(
        "check_id",
        [
            "s3_bucket_public_access",
            "ec2_instance_public_ip",
            "security_group_open_to_0.0.0.0",
            "rds_instance_exposed_to_internet",
            "s3_bucket_anonymous_access",
        ],
    )
    def test_public_markers_classify_public(self, check_id):
        assert classify_exposure(check_id=check_id) is Exposure.PUBLIC

    @pytest.mark.parametrize("check_id", ["s3_bucket_versioning", "ec2_ebs_encryption", "iam_password_policy"])
    def test_non_markers_default_private(self, check_id):
        assert classify_exposure(check_id=check_id) is Exposure.PRIVATE

    def test_resource_type_marker_also_counts(self):
        assert classify_exposure(check_id="x", resource_type="aws_public_ip") is Exposure.PUBLIC

    def test_empty_defaults_private(self):
        assert classify_exposure() is Exposure.PRIVATE
