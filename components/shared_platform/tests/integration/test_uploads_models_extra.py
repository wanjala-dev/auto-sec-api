import pytest


pytestmark = pytest.mark.django_db


def test_file_type_helpers(file_factory):
    pdf = file_factory(file_type="pdf")
    doc = file_factory(file_type="document")

    assert pdf.is_pdf is True
    assert pdf.needs_processing is True
    assert doc.is_document is True
    assert doc.needs_processing is True
