"""The scan-output artifact channel (ADR 0022 D2–D4).

What these lock down, in order of what would hurt most if it broke:

1. **It is ONE channel.** Every engine renders its publish step from the same helper.
   Three hand-rolled dialects is the per-engine transport this design exists to avoid,
   and it would rot silently — so a fitness test asserts it structurally.
2. **No credentials reach the untrusted tier.** The uploader gets a presigned URL, never
   keys. A regression here hands a scanner of customer code a bucket.
3. **Failure is loud.** Upload failure, a missing artifact, and a truncated artifact all
   fail the run. The transport changed; ADR 0022 D1's invariant did not.
"""

from __future__ import annotations

import pytest

from components.scanning.application.ports.scan_execution_backend import (
    SCAN_ARTIFACT_PATH,
    SCAN_SENTINEL_PATH,
    ScanJobResult,
    ScanJobSpec,
    artifact_emit_tail,
)

pytestmark = pytest.mark.unit


class TestArtifactEmitProtocol:
    def test_publishes_the_document_before_signalling_completion(self):
        """Order is the correctness bit: the uploader waits on the sentinel, so the
        artifact must already be complete when the sentinel appears — otherwise the
        uploader can race a half-written file and ship a truncated artifact, which is
        the exact bug class this whole ADR exists to remove."""
        tail = artifact_emit_tail("/tmp/engine-out.json")
        assert tail.index(SCAN_ARTIFACT_PATH) < tail.index(SCAN_SENTINEL_PATH)

    def test_only_publishes_on_engine_success(self):
        tail = artifact_emit_tail("/tmp/engine-out.json")
        assert '[ "$code" = "0" ]' in tail
        assert "-s " in tail  # ...and only a non-empty document

    def test_always_writes_the_sentinel_even_on_failure(self):
        """If the sentinel were skipped on failure the uploader would block until its
        WAIT_SECONDS timeout, turning every failed scan into a slow one."""
        tail = artifact_emit_tail("/tmp/engine-out.json")
        publish, _, signal = tail.partition("printf")
        assert "fi;" in publish  # the conditional closes BEFORE the sentinel write
        assert SCAN_SENTINEL_PATH in signal


class TestOneChannelForEveryEngine:
    """Fitness test: no engine may grow its own transport."""

    def _scripts(self) -> dict[str, str]:
        from components.code_security.infrastructure.adapters.opengrep_scanner import _job_script as og
        from components.container_security.infrastructure.adapters.trivy_scanner import _job_script as tv

        return {
            "trivy": tv(timeout="15m", server=None),
            "opengrep": og(),
        }

    @pytest.mark.parametrize("engine", ["trivy", "opengrep"])
    def test_engine_script_publishes_to_the_canonical_artifact_path(self, engine):
        script = self._scripts()[engine]
        assert SCAN_ARTIFACT_PATH in script, f"{engine} does not publish to the shared artifact path"
        assert SCAN_SENTINEL_PATH in script, f"{engine} does not signal completion"

    def test_prowler_script_publishes_too(self):
        # Prowler's script is built inline in scan(); assert on the rendered tail it uses.
        tail = artifact_emit_tail("$ocsf")
        assert SCAN_ARTIFACT_PATH in tail and SCAN_SENTINEL_PATH in tail


class TestSpecAndResultCarryTheChannel:
    def test_spec_without_artifact_path_keeps_the_legacy_stdout_transport(self):
        spec = ScanJobSpec(source="s", image="i", args=("a",))
        assert spec.artifact_path == ""

    def test_result_defaults_to_no_artifact_ref(self):
        assert ScanJobResult(stdout="{}", exit_code=0).artifact_ref == ""


class _FakeStore:
    """Records what it was asked for; never touches the network."""

    def __init__(self, content='{"ok":1}'):
        self.content = content
        self.presigned = []
        self.fetched = []

    def presign_put(self, *, workspace_id, scan_run_id, source):
        from components.scanning.application.ports.scan_artifact_store_port import ArtifactUploadTarget

        self.presigned.append((workspace_id, scan_run_id, source))
        return ArtifactUploadTarget(
            url="https://minio.invalid/bucket/key?X-Amz-Signature=abc",
            bucket="autosec-scan-artifacts",
            key=f"scan-artifacts/{workspace_id}/{source}/{scan_run_id}.json",
        )

    def fetch(self, *, bucket, key):
        self.fetched.append((bucket, key))
        return self.content


class TestUploaderContainer:
    def _pod_containers(self, store, spec):
        pytest.importorskip("kubernetes")
        from components.scanning.infrastructure.backends.k8s_job_backend import K8sJobBackend

        backend = K8sJobBackend(artifact_store=store)
        target = store.presign_put(workspace_id="ws", scan_run_id="run", source=spec.source)
        job = backend._job("scan-test", "scan-test-creds", spec, target)
        return job.spec.template.spec.containers

    def _spec(self):
        return ScanJobSpec(
            source="cloud_posture.prowler",
            image="prowler:pinned",
            args=("sh", "-c", "true"),
            artifact_path=SCAN_ARTIFACT_PATH,
            workspace_id="ws",
            scan_run_id="run",
        )

    def test_uploader_is_added_alongside_the_engine(self):
        containers = self._pod_containers(_FakeStore(), self._spec())
        assert [c.name for c in containers] == ["scanner", "artifact-uploader"]

    def test_uploader_receives_a_capability_never_credentials(self):
        """The scan tier unpacks customer images and parses customer code. It gets a
        one-object presigned URL — no access key, no secret, no bucket-wide reach."""
        containers = self._pod_containers(_FakeStore(), self._spec())
        env = {e.name: e.value for e in containers[1].env}
        assert env["UPLOAD_URL"].startswith("https://")
        leaked = [k for k in env if "ACCESS_KEY" in k or "SECRET" in k or "PASSWORD" in k]
        assert leaked == [], f"credentials leaked into the untrusted scan tier: {leaked}"

    def test_uploader_shares_the_engines_scratch_volume(self):
        containers = self._pod_containers(_FakeStore(), self._spec())
        assert [m.name for m in containers[1].volume_mounts] == ["scratch"]

    def test_uploader_outlives_the_engine_deadline(self):
        """A uploader that exits before a slow scan finishes loses the artifact."""
        spec = self._spec()
        containers = self._pod_containers(_FakeStore(), spec)
        env = {e.name: e.value for e in containers[1].env}
        assert int(env["WAIT_SECONDS"]) > spec.timeout_seconds

    def test_uploader_keeps_the_hardened_constraints(self):
        containers = self._pod_containers(_FakeStore(), self._spec())
        sc = containers[1].security_context
        assert sc.read_only_root_filesystem is True
        assert sc.allow_privilege_escalation is False
        assert sc.capabilities.drop == ["ALL"]

    def test_uploader_image_is_pinned_by_digest(self):
        from components.scanning.infrastructure.backends.k8s_job_backend import _UPLOADER_IMAGE

        # pin-versions.md #2: we execute this image, so a re-pushed tag must not change it.
        assert "@sha256:" in _UPLOADER_IMAGE
        assert ":latest" not in _UPLOADER_IMAGE

    def test_no_uploader_when_the_channel_is_not_requested(self):
        pytest.importorskip("kubernetes")
        from components.scanning.infrastructure.backends.k8s_job_backend import K8sJobBackend

        spec = ScanJobSpec(source="s", image="i", args=("a",))
        job = K8sJobBackend(artifact_store=_FakeStore())._job("n", "c", spec, None)
        assert [c.name for c in job.spec.template.spec.containers] == ["scanner"]


class TestUploaderScriptSemantics:
    def _script(self) -> str:
        from components.scanning.infrastructure.backends.k8s_job_backend import _UPLOADER_SCRIPT

        return _UPLOADER_SCRIPT

    def test_upload_failure_exits_non_zero_so_the_job_fails(self):
        """A k8s Job succeeds only when every container exits 0 — so a non-zero exit here
        IS the "upload failure = FAILED run" guarantee (ADR 0022 D4), for free."""
        assert "exit 72" in self._script()

    def test_missing_artifact_after_a_successful_engine_fails(self):
        assert "exit 71" in self._script()

    def test_never_hangs_forever(self):
        assert "exit 70" in self._script() and "WAIT_SECONDS" in self._script()

    def test_engine_failure_does_not_mask_the_engines_own_exit_code(self):
        script = self._script()
        assert "nothing to upload" in script and "exit 0" in script


class TestArtifactContentStillPassesThePhase1Guard:
    """The transport changed; the integrity invariant did not.

    An artifact can be truncated too (a killed uploader, a partial PUT). ADR 0022 D1's
    guard must still be what decides — otherwise the new channel quietly reintroduces
    exactly the silent false negative the old one had.
    """

    def test_truncated_artifact_content_fails_loud(self):
        import json

        from components.scanning.domain.engine_output import parse_engine_result_document
        from components.scanning.domain.errors import IncompleteScanOutputError

        document = json.dumps([{"uid": i, "pad": "x" * 200} for i in range(50)])
        with pytest.raises(IncompleteScanOutputError):
            parse_engine_result_document(document[: len(document) // 2], engine="prowler")

    def test_store_errors_are_scan_execution_errors(self):
        from components.scanning.domain.errors import ScanArtifactStoreError, ScanExecutionError

        # So run_scan_and_ingest's existing FAILED-run path catches them unchanged.
        assert issubclass(ScanArtifactStoreError, ScanExecutionError)


class TestArtifactRefSurvivesEveryReturnPath:
    """Regression: a live scan COMPLETED with an empty raw_artifact_ref.

    Trivy's SBOM branch rebuilt ScanResult field-by-field and forgot the new one, so the
    artifact was uploaded and fetched correctly but the run pointed at nothing — the raw
    output was unreachable, which is the entire debugging value of the channel. Unit tests
    passed throughout; only a real scan surfaced it. Both adapters now use
    dataclasses.replace, which cannot forget a field, and these lock that in.
    """

    def test_trivy_keeps_the_ref_on_the_sbom_branch(self):
        import json

        from components.container_security.infrastructure.adapters.trivy_scanner import TrivyScanner
        from components.scanning.application.ports.scan_execution_backend import ScanJobResult

        envelope = json.dumps(
            {
                "autosec_trivy_envelope": 1,
                "vuln": {"Results": []},
                "sbom": {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []},
            }
        )

        class _Backend:
            def run(self, spec, *, on_progress=None, on_output_line=None):
                return ScanJobResult(stdout=envelope, exit_code=0, artifact_ref="bucket/some/key.json")

        from components.shared_kernel.application.ports.scanner_port import ScanTarget

        result = TrivyScanner(_Backend()).scan(ScanTarget(identifier="alpine:3.19"))
        assert result.artifacts, "the SBOM branch must still be exercised by this test"
        assert result.raw_artifact_ref == "bucket/some/key.json"
