"""Unit tests for ``FaithfulnessVerifier`` (SEE-171).

Pure domain tests — no DB, no LLM, no framework. They prove the
slot-and-verify guard: numbers/money/dates are flagged strictly (and flip
``ok``), proper names are flagged softly (reported, not gating), value
comparison is normalisation-aware ($50,000 ↔ 50000), and HTML tags are
stripped before extraction.
"""

from __future__ import annotations

from components.agents.domain.services.faithfulness_verifier import (
    FaithfulnessVerifier,
    FaithfulnessReport,
)


def _verify(body, grounding):
    return FaithfulnessVerifier().verify(
        generated_html=body, grounding_texts=grounding
    )


class TestNumbers:
    def test_number_not_in_context_is_flagged_and_ok_false(self):
        report = _verify(
            "<p>We raised $80,000 this quarter.</p>",
            ["The campaign raised $50,000 from two donors."],
        )
        assert report.ok is False
        assert any("80,000" in n for n in report.unsupported_numbers)
        assert report.checked >= 1

    def test_all_numbers_present_is_ok_true(self):
        report = _verify(
            "<p>We raised $50,000 and helped 12 children.</p>",
            ["The campaign raised 50,000. It helped 12 children this year."],
        )
        assert report.ok is True
        assert report.unsupported_numbers == ()

    def test_money_normalisation_comma_vs_plain(self):
        # $50,000 in the copy supported by bare 50000 in the source.
        report = _verify(
            "<p>$50,000 was granted.</p>", ["A grant of 50000 was awarded."]
        )
        assert report.ok is True

    def test_money_normalisation_trailing_decimal_zeros(self):
        # 45000.00 in the source supports 45,000 in the copy.
        report = _verify(
            "<p>Total raised 45,000.</p>", ["Total raised: 45000.00"]
        )
        assert report.ok is True

    def test_year_not_in_context_is_flagged(self):
        report = _verify(
            "<p>Founded in 1998.</p>", ["The organization helps families."]
        )
        assert report.ok is False
        assert "1998" in report.unsupported_numbers

    def test_percentage_supported_by_bare_number(self):
        report = _verify(
            "<p>40% of funds went to school fees.</p>",
            ["Roughly 40 percent went to school fees."],
        )
        assert report.ok is True

    def test_empty_grounding_flags_every_figure(self):
        report = _verify("<p>We gave $1,200 to 3 schools.</p>", [])
        assert report.ok is False
        # both the money token and the count are unsupported
        assert len(report.unsupported_numbers) >= 2

    def test_no_numbers_is_ok_true(self):
        report = _verify(
            "<p>Thank you for your generous support.</p>", ["Some context."]
        )
        assert report.ok is True
        assert report.unsupported_numbers == ()


class TestProperNouns:
    def test_unknown_multiword_name_soft_flagged_not_ok_breaking(self):
        report = _verify(
            "<p>Thanks to the Mastercard Foundation for the gift.</p>",
            ["A generous donor supported the literacy program."],
        )
        # name surfaced for review …
        assert any("Mastercard Foundation" in n for n in report.unsupported_names)
        # … but names are SOFT: ok is driven by numbers, none here → True
        assert report.ok is True

    def test_known_name_in_context_not_flagged(self):
        report = _verify(
            "<p>Thanks to the Mastercard Foundation.</p>",
            ["The Mastercard Foundation gave a grant this year."],
        )
        assert report.unsupported_names == ()

    def test_salutations_and_sentence_starts_not_flagged(self):
        # "Dear Amina" → leading stopword stripped → single word → skipped.
        # "Thank You" → all stopwords → skipped.
        report = _verify(
            "<p>Dear Amina, Thank You for everything.</p>",
            ["Some unrelated context."],
        )
        assert report.unsupported_names == ()

    def test_single_capitalized_word_not_flagged(self):
        report = _verify(
            "<p>She visited Nairobi last week.</p>", ["Unrelated context."]
        )
        assert report.unsupported_names == ()


class TestHtmlStripping:
    def test_tags_stripped_before_checking(self):
        report = _verify(
            '<div class="x"><strong>$50,000</strong> raised in 2026.</div>',
            ["We raised 50000 in 2026."],
        )
        assert report.ok is True
        # tag/attribute tokens ('x') must not leak into name checks
        assert report.unsupported_names == ()

    def test_html_entities_unescaped(self):
        report = _verify(
            "<p>Mary &amp; John gave $20.</p>", ["Mary & John gave 20 dollars."]
        )
        assert report.ok is True


class TestReportShape:
    def test_as_dict_shape(self):
        report = _verify("<p>$5 raised.</p>", ["Nothing here."])
        data = report.as_dict()
        assert set(data) == {
            "ok",
            "unsupported_numbers",
            "unsupported_names",
            "checked",
        }
        assert isinstance(data["unsupported_numbers"], list)
        assert isinstance(data["unsupported_names"], list)
        assert isinstance(data["checked"], int)

    def test_none_grounding_is_safe(self):
        report = _verify("<p>Plain copy, no figures.</p>", None)
        assert isinstance(report, FaithfulnessReport)
        assert report.ok is True
