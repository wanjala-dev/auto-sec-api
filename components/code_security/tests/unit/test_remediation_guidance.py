"""Fitness tests for the remediation-guidance corpus (ADR 0019 D5).

These are the tests that let the corpus GROW safely. Guidance is prose plus
regexes, and prose rots quietly: someone edits a class's recommendation, the
anti-pattern beside it no longer matches the wrong example, and the corpus keeps
passing while silently protecting nothing. CodeQL's query-help guidance makes the
same point about its own before/after examples — "make sure that the examples are
actually consistent with what the query does, for example by including them in
your unit tests".

So every class is required to be SELF-CONSISTENT: its own `wrong` example must trip
one of its own anti-patterns, and its own `correct` example must trip none. A class
whose prose and regexes disagree cannot land, and neither can one whose anti-pattern
would veto the very fix it recommends — the expensive failure, because a false
positive here rejects real fixes for as long as nobody notices.

Coverage is enforced the same way: every rule in every first-party pack must bind to
a class or carry an explicit waiver. Adding a rule without deciding its remediation
class fails here, at authoring time, instead of surfacing as a wrong patch in a
customer's repository.
"""

from __future__ import annotations

import re

import pytest
import yaml

from components.code_security.domain.remediation_guidance import (
    check_patch,
    guidance_for,
    patch_parses,
    prompt_block,
    remediation_classes,
    rule_bindings,
    unmapped_rules,
)
from components.code_security.infrastructure.services.ruleset import _RULES_DIR

pytestmark = pytest.mark.unit


def _pack_rule_ids() -> list[str]:
    manifest = yaml.safe_load((_RULES_DIR / "packs.yaml").read_text()) or {}
    ids: list[str] = []
    for pack in manifest.get("packs") or []:
        document = yaml.safe_load((_RULES_DIR / str(pack["file"])).read_text()) or {}
        ids.extend(str(rule["id"]) for rule in document.get("rules") or [])
    return ids


class TestCorpusIsSelfConsistent:
    """The guarantee that lets the corpus grow: guidance that lies cannot land."""

    def test_every_class_anti_pattern_compiles(self):
        for name, guidance in remediation_classes().items():
            for anti in guidance.anti_patterns:
                try:
                    re.compile(anti.regex)
                except re.error as exc:  # pragma: no cover - the assert is the point
                    pytest.fail(f"class {name}: anti-pattern {anti.regex!r} does not compile ({exc})")

    def test_every_wrong_example_trips_its_own_anti_pattern(self):
        """The anti-example is the spec for the regex — they must agree."""
        for name, guidance in remediation_classes().items():
            if not guidance.anti_patterns:
                continue
            hit = check_patch(guidance.wrong, guidance)
            assert hit is not None, (
                f"class {name}: its own `wrong` example is not caught by any of its anti_patterns — "
                "the regex and the prose have drifted apart"
            )

    def test_no_correct_example_trips_its_own_anti_pattern(self):
        """The expensive failure mode: an anti-pattern that vetoes the real fix."""
        for name, guidance in remediation_classes().items():
            hit = check_patch(guidance.correct, guidance)
            assert hit is None, (
                f"class {name}: its own recommended `correct` example is rejected by anti-pattern "
                f"{hit.regex!r} ({hit.why}) — this would reject real fixes"
            )

    def test_every_class_carries_a_recommendation_and_reason(self):
        for name, guidance in remediation_classes().items():
            assert guidance.recommendation.strip(), f"class {name} has no recommendation"
            assert guidance.why.strip(), f"class {name} does not say why the distinction matters"


class TestCoverage:
    """Adding a rule without deciding its remediation class must fail HERE."""

    def test_every_first_party_rule_binds_to_a_class_or_is_waived(self):
        bound = rule_bindings()
        waived = unmapped_rules()
        missing = [rid for rid in _pack_rule_ids() if rid not in bound and rid not in waived]
        assert not missing, (
            "these pack rules have no remediation class (add a line to bindings.yaml, or record a "
            f"reason under `unmapped:`): {missing}"
        )

    def test_bindings_do_not_reference_retired_rules(self):
        """A binding for a rule that no longer exists is dead weight — catch the drift both ways."""
        pack_ids = set(_pack_rule_ids())
        stale = [rid for rid in rule_bindings() if rid not in pack_ids]
        assert not stale, f"bindings.yaml binds rules that are not in any pack: {stale}"

    def test_every_declared_class_is_actually_used(self):
        used = set(rule_bindings().values())
        # CWE fallbacks count as use — they are how imported packs resolve.
        doc = yaml.safe_load((_RULES_DIR / "remediation" / "bindings.yaml").read_text()) or {}
        used |= set((doc.get("cwe") or {}).values())
        orphans = [name for name in remediation_classes() if name not in used]
        assert not orphans, f"remediation classes nothing binds to: {orphans}"


class TestResolution:
    def test_explicit_rule_binding_wins(self):
        guidance = guidance_for("autosec.python.sql-execute-format")
        assert guidance is not None
        assert guidance.remediation_class == "parameterise-values-quote-identifiers"
        assert guidance.source == "rule"

    def test_cwe_fallback_covers_an_unbound_rule(self):
        """The scale lever: an imported pack's rule resolves with zero authoring."""
        guidance = guidance_for("thirdparty.python.some-new-sqli-rule", ["CWE-89: SQL Injection"])
        assert guidance is not None
        assert guidance.remediation_class == "parameterise-values-quote-identifiers"
        assert guidance.source == "cwe"

    @pytest.mark.parametrize("cwes", [["CWE-78"], ["cwe-78"], "CWE_78", ["CWE-78: OS Command Injection"]])
    def test_cwe_shapes_all_normalise(self, cwes):
        """Registry rules spell CWEs several ways; all of them must resolve."""
        guidance = guidance_for("thirdparty.rule", cwes)
        assert guidance is not None and guidance.remediation_class == "argv-list-not-shell"

    def test_unknown_rule_with_no_cwe_is_a_clean_miss(self):
        """Degraded, never broken — an unmapped rule still produces a fix."""
        assert guidance_for("thirdparty.rule.unknown") is None
        assert prompt_block(None) == ""
        assert check_patch("anything at all", None) is None


class TestTheDogfoodRegression:
    """The patches that shipped wrong must now be caught. PR #866 / #869 / #867."""

    def test_866_identifier_bound_as_parameter_is_rejected(self):
        guidance = guidance_for("autosec.python.sql-execute-format")
        hit = check_patch('cursor.execute("CREATE SCHEMA IF NOT EXISTS %s", (schema,))', guidance)
        assert hit is not None
        assert "identifier" in hit.why.lower()

    def test_869_same_error_different_spelling_is_rejected(self):
        guidance = guidance_for("autosec.python.sql-execute-format")
        hit = check_patch("cursor.execute('SET search_path to %s', [schema])", guidance)
        assert hit is not None

    def test_867_verification_against_an_empty_key_is_rejected(self):
        guidance = guidance_for("autosec.python.jwt-verify-disabled")
        hit = check_patch(
            "decoded = jwt.decode(id_token, '', algorithms=['ES256'], options={'verify_signature': True})",
            guidance,
        )
        assert hit is not None

    def test_the_correct_sql_fix_passes(self):
        """The point is not to reject SQL fixes — it is to reject the wrong one."""
        guidance = guidance_for("autosec.python.sql-execute-format")
        correct = (
            "from psycopg import sql\n"
            'cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))'
        )
        assert check_patch(correct, guidance) is None

    def test_a_bound_VALUE_is_not_mistaken_for_an_identifier(self):
        """The anti-pattern must not veto ordinary, correct parameterisation."""
        guidance = guidance_for("autosec.python.sql-execute-format")
        assert check_patch('cursor.execute("SELECT * FROM t WHERE id = %s", [user_id])', guidance) is None

    def test_870_key_bearing_jwt_fix_passes(self):
        """The retry that replaced #867 names a real key source — it must survive."""
        guidance = guidance_for("autosec.python.jwt-verify-disabled")
        patch = "decoded = jwt.decode(id_token, settings.SOCIAL_AUTH_APPLE_PUBLIC_KEY, algorithms=['RS256'])"
        assert check_patch(patch, guidance) is None


class TestPromptBlock:
    def test_block_carries_recommendation_correct_and_anti_example(self):
        block = prompt_block(guidance_for("autosec.python.sql-execute-format"))
        assert "sql.Identifier" in block, "the correct shape must be shown"
        assert "CREATE SCHEMA IF NOT EXISTS %s" in block, "the contrastive near-miss must be shown"

    def test_the_correct_shape_is_the_last_code_the_model_reads(self):
        """Contrastive ordering, measured not stylistic: the 2026-08-16 baseline
        caught the model returning the block's wrong example byte-for-byte as
        its fix when the wrong example appeared after the correct one. The
        near-miss is a labeled pair (wrong + why, immediately followed by the
        correct shape); the correct shape comes last because recency wins."""
        block = prompt_block(guidance_for("autosec.python.sql-execute-format"))
        wrong_at = block.index("CREATE SCHEMA IF NOT EXISTS %s")
        why_at = block.index("why it fails:")
        # Anchor on the section marker, not a code token — "sql.Identifier"
        # also appears in the recommendation line above the pair.
        correct_at = block.index("the correct SHAPE to produce instead")
        assert wrong_at < why_at < correct_at

    def test_no_pink_elephant_phrasing(self):
        """Free-standing negative instructions are the fixation form our own
        prompt-hygiene rules ban (§12.2); the near-miss is labeled, not
        forbidden."""
        block = prompt_block(guidance_for("autosec.python.sql-execute-format"))
        assert "do not produce this" not in block.lower()


class TestExemplarsCannotBePasted:
    """The failure this class of test exists for, observed live.

    With guidance active, the JWT advisor produced ``key = fetch_jwks_key('kid')``
    — a verbatim copy of the worked example's INVENTED helper, which does not exist
    in the target codebase. No anti-pattern catches it: the SHAPE is right and only
    the symbol is fictional. Few-shot exemplars get copied; that is what they are
    for. So an exemplar must be written such that copying it cannot produce valid
    code, and anything codebase-specific must be declared as a placeholder.
    """

    #: Real APIs the exemplars are allowed to name. Deliberately a small allowlist:
    #: adding a class that calls something new means adding it here, which forces
    #: the question "is this a real API, or did I just invent a helper?".
    REAL_APIS = {
        "json.loads",
        "yaml.safe_load",
        "yaml.load",
        "subprocess.run",
        "ast.literal_eval",
        "pickle.loads",
        "jwt.decode",
        "cursor.execute",
        "sql.SQL",
        "sql.Identifier",
        "format",  # psycopg Composed.format — the identifier composer, genuinely real
        "format_html",
        "tempfile.NamedTemporaryFile",
        "requests.get",
        "execFile",
        "JSON.parse",
        "db.Query",
        "fmt.Sprintf",
        "escape",
        "mark_safe",
        "exec",
        "eval",
        "os.system",
        "new Function",
        "replace",
        "tempfile.mktemp",
    }

    @staticmethod
    def _code_only(example: str) -> str:
        """Drop comment prose — an exemplar's comments are English, not API calls.

        Without this the scan reads "…for the issuer (a JWKS fetch…" as a call to
        ``issuer()``. A checker that cries wolf gets muted, which would cost us the
        real signal.
        """
        lines = []
        for line in example.splitlines():
            for marker in ("#", "//"):
                if marker in line:
                    line = line.split(marker, 1)[0]
            lines.append(line)
        return "\n".join(lines)

    def test_no_exemplar_invents_a_helper_function(self):
        call = re.compile(r"([A-Za-z_][\w.]*)\s*\(")
        for name, guidance in remediation_classes().items():
            for symbol in call.findall(self._code_only(guidance.correct)):
                assert symbol in self.REAL_APIS, (
                    f"class {name}: `correct` calls {symbol!r}, which is not a known real API. "
                    "If it is real, add it to REAL_APIS; if it is a stand-in, write it as a "
                    "placeholder so it cannot be pasted into a patch."
                )

    def test_declared_placeholders_actually_appear_in_the_example(self):
        for name, guidance in remediation_classes().items():
            for placeholder in guidance.placeholders:
                assert placeholder in guidance.correct, (
                    f"class {name}: declares placeholder {placeholder!r} that is not in `correct` — "
                    "a stale declaration means the prompt promises a substitution that never happens"
                )

    def test_placeholders_are_syntactically_uncopyable(self):
        """A placeholder must BREAK if pasted — that is what makes it safe."""
        for name, guidance in remediation_classes().items():
            for placeholder in guidance.placeholders:
                assert placeholder.startswith("<") and placeholder.endswith(">"), (
                    f"class {name}: placeholder {placeholder!r} looks like valid code. Use angle "
                    "brackets so copying it verbatim cannot compile."
                )

    def test_the_jwt_class_declares_its_key_source_as_a_placeholder(self):
        """Regression lock on the exact live failure."""
        guidance = guidance_for("autosec.python.jwt-verify-disabled")
        assert guidance.placeholders, "the JWT exemplar must not hand the model a copyable key source"
        assert "fetch_jwks_key" not in guidance.correct


class TestPromptCarriesTheGeneralConstraints:
    """A concrete example out-competes a general instruction read earlier.

    Both live patches came back UNVERIFIED for referencing none of the finding's
    specifics — the system prompt asks for the rule and file by name, but the
    guidance block was appended after it and dominated. The block therefore has to
    restate the constraints it would otherwise crowd out.
    """

    def test_block_forbids_copying_identifiers_from_the_example(self):
        block = prompt_block(guidance_for("autosec.python.jwt-verify-disabled"))
        assert "never copy a name from the" in block
        assert "illustration" in block or "illustrative" in block

    def test_block_restates_the_grounding_requirement(self):
        block = prompt_block(guidance_for("autosec.python.sql-execute-format"))
        assert "name the rule and the flagged file" in block

    def test_block_lists_placeholders_when_the_class_has_them(self):
        block = prompt_block(guidance_for("autosec.python.jwt-verify-disabled"))
        assert "PLACEHOLDERS" in block
        assert "<AUDIENCE>" in block

    def test_block_omits_the_placeholder_line_when_there_are_none(self):
        block = prompt_block(guidance_for("autosec.python.tempfile-mktemp"))
        assert "PLACEHOLDERS" not in block


class TestTheSyntaxOracleAbstainsRatherThanPassing:
    """A patch nobody could parse must not look like one that parsed clean.

    `patch_parses` returned `ok=True` for EVERY non-Python language — not "fail",
    not "unknown", but pass. So a Terraform, JavaScript, Go or YAML patch came out
    of the L1 oracle indistinguishable from a Python patch that genuinely parsed.

    The original decision was sound and honestly documented ("it is the only
    language whose parser ships in this image; claiming coverage we do not have
    would be worse than the gap"). What was missing is that the RESULT never said
    so — which left this the last place in the pipeline answering "fine" when it
    meant "unknown", after `priced=False`, `verification="unverified"` and the
    patch attestation all learned to distinguish the two.
    """

    def test_python_patch_is_actually_checked(self):
        v = patch_parses(patch_code="x = 1", before_code="x = 2", language="python")

        assert v.ok is True
        assert v.checked is True

    def test_non_python_abstains_and_says_so(self):
        v = patch_parses(patch_code='resource "aws_s3_bucket" "b" {}', before_code="", language="terraform")

        assert v.ok is True  # still flows — withholding the artifact was never the policy
        assert v.checked is False
        assert "not checked" in v.reason.lower()

    def test_the_abstention_names_the_language(self):
        """An operator reading 'no parser available' must know for WHAT."""
        assert "javascript" in patch_parses(patch_code="a", before_code="b", language="JavaScript").reason.lower()

    def test_unknown_language_abstains_too(self):
        v = patch_parses(patch_code="a", before_code="b", language="")

        assert v.checked is False
        assert "unknown-language" in v.reason

    def test_a_genuinely_broken_python_patch_still_fails(self):
        """The abstention must not weaken the case the oracle exists for: the
        before-fragment parses, the after-fragment does not."""
        v = patch_parses(patch_code="def broken(:", before_code="def fine():\n    pass", language="python")

        assert v.ok is False
        assert v.checked is True
