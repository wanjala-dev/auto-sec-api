"""Unit tests for FileClassification value object and classify_file function."""

from __future__ import annotations

import pytest

from components.shared_platform.domain.value_objects.file_classification import (
    ALLOWED_CONTENT_TYPES,
    CONTENT_TYPE_MAP,
    FileClassification,
    classify_file,
)


class TestFileClassificationValueObject:
    """Test suite for FileClassification immutable value object."""

    def test_file_classification_creation(self):
        """Should create FileClassification with all fields."""
        classification = FileClassification(
            content_type="application/pdf",
            file_type="pdf",
            is_allowed=True,
            requires_processing=True,
        )

        assert classification.content_type == "application/pdf"
        assert classification.file_type == "pdf"
        assert classification.is_allowed is True
        assert classification.requires_processing is True

    def test_file_classification_is_immutable(self):
        """Should raise error when trying to modify fields."""
        classification = FileClassification(
            content_type="application/pdf",
            file_type="pdf",
            is_allowed=True,
            requires_processing=True,
        )

        with pytest.raises(Exception):
            classification.file_type = "document"

        with pytest.raises(Exception):
            classification.is_allowed = False

    def test_file_classification_equality(self):
        """Should compare based on all fields."""
        c1 = FileClassification(
            content_type="image/png",
            file_type="image",
            is_allowed=True,
            requires_processing=False,
        )
        c2 = FileClassification(
            content_type="image/png",
            file_type="image",
            is_allowed=True,
            requires_processing=False,
        )

        assert c1 == c2

    def test_file_classification_inequality_on_different_content_type(self):
        """Should be unequal when content_type differs."""
        c1 = FileClassification(
            content_type="image/png",
            file_type="image",
            is_allowed=True,
            requires_processing=False,
        )
        c2 = FileClassification(
            content_type="image/jpeg",
            file_type="image",
            is_allowed=True,
            requires_processing=False,
        )

        assert c1 != c2


class TestClassifyFileFunction:
    """Test suite for classify_file() pure function."""

    # Test image MIME types
    def test_classify_jpeg_image(self):
        """Should classify JPEG as image."""
        result = classify_file("image/jpeg")

        assert result.content_type == "image/jpeg"
        assert result.file_type == "image"
        assert result.is_allowed is True
        assert result.requires_processing is False

    def test_classify_png_image(self):
        """Should classify PNG as image."""
        result = classify_file("image/png")

        assert result.content_type == "image/png"
        assert result.file_type == "image"
        assert result.is_allowed is True
        assert result.requires_processing is False

    def test_classify_svg_image(self):
        """Should classify SVG as image."""
        result = classify_file("image/svg+xml")

        assert result.content_type == "image/svg+xml"
        assert result.file_type == "image"
        assert result.is_allowed is True
        assert result.requires_processing is False

    # Test PDF
    def test_classify_pdf(self):
        """Should classify PDF and mark for processing."""
        result = classify_file("application/pdf")

        assert result.content_type == "application/pdf"
        assert result.file_type == "pdf"
        assert result.is_allowed is True
        assert result.requires_processing is True

    # Test document MIME types
    def test_classify_doc_word_document(self):
        """Should classify .doc as document."""
        result = classify_file("application/msword")

        assert result.content_type == "application/msword"
        assert result.file_type == "document"
        assert result.is_allowed is True
        assert result.requires_processing is True

    def test_classify_docx_word_document(self):
        """Should classify .docx as document."""
        result = classify_file(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

        assert result.file_type == "document"
        assert result.is_allowed is True
        assert result.requires_processing is True

    def test_classify_csv_document(self):
        """Should classify CSV as document."""
        result = classify_file("text/csv")

        assert result.content_type == "text/csv"
        assert result.file_type == "document"
        assert result.is_allowed is True
        assert result.requires_processing is True

    def test_classify_csv_application_variant(self):
        """Should classify application/csv as document."""
        result = classify_file("application/csv")

        assert result.file_type == "document"
        assert result.is_allowed is True
        assert result.requires_processing is True

    def test_classify_xls_excel_document(self):
        """Should classify .xls as document."""
        result = classify_file("application/vnd.ms-excel")

        assert result.file_type == "document"
        assert result.is_allowed is True
        assert result.requires_processing is True

    def test_classify_xlsx_excel_document(self):
        """Should classify .xlsx as document."""
        result = classify_file(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        assert result.file_type == "document"
        assert result.is_allowed is True
        assert result.requires_processing is True

    # Test unknown/disallowed types
    def test_classify_unknown_type(self):
        """Should classify unknown MIME type as 'other' and disallow."""
        result = classify_file("application/unknown")

        assert result.content_type == "application/unknown"
        assert result.file_type == "other"
        assert result.is_allowed is False
        assert result.requires_processing is False

    def test_classify_executable_disallowed(self):
        """Should classify executables as disallowed."""
        result = classify_file("application/x-msdownload")

        assert result.file_type == "other"
        assert result.is_allowed is False

    def test_classify_arbitrary_text_type(self):
        """Should classify arbitrary text types as 'other' and disallow."""
        result = classify_file("text/plain")

        assert result.file_type == "other"
        assert result.is_allowed is False
        assert result.requires_processing is False

    def test_classify_video_disallowed(self):
        """Should classify video types as disallowed."""
        result = classify_file("video/mp4")

        assert result.file_type == "other"
        assert result.is_allowed is False

    def test_classify_audio_disallowed(self):
        """Should classify audio types as disallowed."""
        result = classify_file("audio/mpeg")

        assert result.file_type == "other"
        assert result.is_allowed is False

    # Test empty and edge cases
    def test_classify_empty_string(self):
        """Should classify empty string as 'other' and disallow."""
        result = classify_file("")

        assert result.content_type == ""
        assert result.file_type == "other"
        assert result.is_allowed is False

    def test_classify_case_sensitivity(self):
        """MIME types should be matched exactly (case-sensitive)."""
        # MIME types are typically lowercase, but test the function's behavior
        result = classify_file("IMAGE/JPEG")  # Uppercase variant

        assert result.file_type == "other"
        assert result.is_allowed is False

    def test_classify_with_charset_parameter(self):
        """Should match MIME type without charset parameter."""
        # In practice, MIME types might include charset, but our mapping is simple
        result = classify_file("text/csv; charset=utf-8")

        # This won't match because the function does exact matching
        assert result.file_type == "other"
        assert result.is_allowed is False

    # Test all mapped types are consistently configured
    def test_all_allowed_types_are_in_content_type_map(self):
        """All ALLOWED_CONTENT_TYPES should exist in CONTENT_TYPE_MAP."""
        for content_type in ALLOWED_CONTENT_TYPES:
            assert content_type in CONTENT_TYPE_MAP

    def test_all_content_type_map_entries_are_allowed(self):
        """All CONTENT_TYPE_MAP entries should be in ALLOWED_CONTENT_TYPES."""
        for content_type in CONTENT_TYPE_MAP.keys():
            assert content_type in ALLOWED_CONTENT_TYPES

    def test_processing_required_only_for_pdf_and_document(self):
        """Only PDF and document types should require processing."""
        for content_type in ALLOWED_CONTENT_TYPES:
            result = classify_file(content_type)

            if result.file_type in ("pdf", "document"):
                assert result.requires_processing is True
            else:
                assert result.requires_processing is False

    def test_all_allowed_types_have_is_allowed_true(self):
        """All ALLOWED_CONTENT_TYPES should classify as is_allowed=True."""
        for content_type in ALLOWED_CONTENT_TYPES:
            result = classify_file(content_type)
            assert result.is_allowed is True

    # Test consistency of classification results
    def test_consistent_classification_results(self):
        """Calling classify_file multiple times should yield identical results."""
        content_type = "application/pdf"

        result1 = classify_file(content_type)
        result2 = classify_file(content_type)
        result3 = classify_file(content_type)

        assert result1 == result2 == result3

    def test_return_type_is_file_classification(self):
        """classify_file should always return FileClassification instance."""
        for content_type in [
            "image/jpeg",
            "application/pdf",
            "text/csv",
            "unknown/type",
            "",
        ]:
            result = classify_file(content_type)
            assert isinstance(result, FileClassification)
