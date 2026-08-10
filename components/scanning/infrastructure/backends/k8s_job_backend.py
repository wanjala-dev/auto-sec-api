"""K8sJobBackend — run the engine as an ephemeral, hardened Kubernetes Job (ADR 0006 D3).

The production substrate. For each scan it: creates a short-lived Secret with the vended
creds, renders a throwaway Job (mirroring auto-sec-infra scan-job-template — non-root,
readOnlyRootFilesystem, drop ALL caps, seccomp RuntimeDefault, cpu/mem/ephemeral-storage
limits, activeDeadlineSeconds, automountServiceAccountToken:false, gVisor runtimeClass,
the ``autosec-scan`` label the default-deny NetworkPolicy selects), waits for completion,
collects the pod's stdout (the scanner's raw output), deletes the Secret, and lets the Job
self-GC (ttlSecondsAfterFinished). Untrusted work runs only inside this pod — no DB/broker
creds, no app code.

Requires the ``kubernetes`` client + in-cluster RBAC (the ``scanning`` ServiceAccount).
Integration-tested on the cluster, not in unit CI (which uses LocalSubprocessBackend).
"""

from __future__ import annotations

import logging
import os
import time

from components.scanning.application.ports.scan_execution_backend import (
    OutputLineCallback,
    ProgressCallback,
    ScanExecutionBackend,
    ScanJobResult,
    ScanJobSpec,
)

logger = logging.getLogger(__name__)

_NAMESPACE = os.environ.get("SCAN_JOB_NAMESPACE", "autosec")
_RUNTIME_CLASS = os.environ.get("SCAN_JOB_RUNTIME_CLASS") or None  # e.g. "gvisor" when available
_POLL_SECONDS = 3
# Exit code reported when the Job's output could not be RETRIEVED (pod already gone, log
# read errored) — distinct from the engine's own non-zero exit so an operator can tell
# "the scanner failed" from "we lost the scanner's output". Either way: a FAILED run.
_EXIT_OUTPUT_UNAVAILABLE = 125

# The uploader co-container image (ADR 0022 D3). An OFF-THE-SHELF official image with a
# real HTTP client, deliberately not a hand-built one: it needs to do exactly one thing
# (PUT a file to a presigned URL), so owning a Dockerfile, an ECR repo and a build path
# for it would be pure supply-chain surface for no capability. curl is also the smallest
# credible choice (~24 MB) and pulls fast on every scan pod.
#
# Pinned by version AND digest — we execute it, which is the pin-versions.md bar. Note we
# hand it a presigned URL, never credentials, so even a compromised uploader can only
# write the one key it was minted for.
_UPLOADER_IMAGE = os.environ.get(
    "SCAN_ARTIFACT_UPLOADER_IMAGE",
    "curlimages/curl:8.11.1@sha256:c1fe1679c34d9784c1b0d1e5f62ac0a79fca01fb6377cdd33e90473c6f9f9a69",
)

# The Job-side protocol, in ONE place (the engine side of it is rendered by
# ``artifact_emit_tail`` on the port, so all three engines speak it identically).
_SENTINEL_PATH = "/tmp/.autosec-scan-complete"

# POSIX sh (the curl image is alpine/busybox). Nothing untrusted is interpolated: every
# value arrives via env and is expanded quoted. Distinct exit codes so a failure is
# diagnosable from the Job's own status: 70 = engine never signalled, 71 = engine claimed
# success but wrote no artifact, 72 = the upload itself failed.
_UPLOADER_SCRIPT = """\
set -u
waited=0
while [ ! -f "$SENTINEL_PATH" ]; do
  waited=$((waited+1))
  if [ "$waited" -ge "$WAIT_SECONDS" ]; then
    echo "artifact-uploader: timed out waiting for the engine sentinel" >&2
    exit 70
  fi
  sleep 1
done
code=$(cat "$SENTINEL_PATH" 2>/dev/null || echo 1)
if [ "$code" != "0" ]; then
  # The engine container already exits non-zero, which fails the Job on its own. Exiting
  # 0 here keeps the engine's real exit code as the reported cause instead of masking it.
  echo "artifact-uploader: engine exited $code - nothing to upload" >&2
  exit 0
fi
if [ ! -s "$ARTIFACT_PATH" ]; then
  echo "artifact-uploader: engine reported success but $ARTIFACT_PATH is missing or empty" >&2
  exit 71
fi
bytes=$(wc -c < "$ARTIFACT_PATH")
if ! curl -sS --fail-with-body -X PUT -T "$ARTIFACT_PATH" \
     -H "Content-Type: application/json" "$UPLOAD_URL" >&2; then
  echo "artifact-uploader: PUT failed for $ARTIFACT_PATH ($bytes bytes)" >&2
  exit 72
fi
echo "artifact-uploader: uploaded $bytes bytes"
"""


class K8sJobBackend(ScanExecutionBackend):
    def __init__(self, artifact_store=None):
        # Injectable for tests; resolved lazily from the provider in production so
        # constructing a backend never requires object storage to be reachable.
        self._store = artifact_store

    def run(
        self,
        spec: ScanJobSpec,
        *,
        on_progress: ProgressCallback | None = None,
        on_output_line: OutputLineCallback | None = None,
    ) -> ScanJobResult:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()

        batch = client.BatchV1Api()
        core = client.CoreV1Api()

        # Deterministic, DNS-safe name unique to this invocation.
        suffix = str(abs(hash((spec.source, spec.args))) % 10_000_000)
        name = f"scan-{spec.source.replace('.', '-').replace('_', '-')}-{suffix}"[:60]
        secret_name = f"{name}-creds"

        # The artifact channel (ADR 0022 D2): mint a one-object write capability BEFORE the
        # Job exists, so the untrusted pod is handed a capability rather than credentials.
        upload_target = None
        if spec.artifact_path:
            upload_target = self._artifact_store().presign_put(
                workspace_id=spec.workspace_id or "unscoped",
                scan_run_id=spec.scan_run_id or name,
                source=spec.source,
            )

        self._create_secret(core, secret_name, spec.secret_env)
        try:
            batch.create_namespaced_job(_NAMESPACE, self._job(name, secret_name, spec, upload_target))
            timed_out = self._wait(batch, name, spec.timeout_seconds, on_progress)
            stdout, exit_code = self._collect(batch, core, name)
        finally:
            self._delete_secret(core, secret_name)
            self._delete_job(batch, name)

        # Prefer the artifact over pod-log stdout whenever the channel was used. The pod log
        # stays a diagnostic (and is what the failure branch reports), but it is NOT the
        # result transport any more — that is the whole point: it truncates at the kubelet's
        # containerLogMaxSize with no error, under-reporting on the biggest accounts.
        if upload_target is not None and not timed_out and exit_code == 0:
            stdout = self._artifact_store().fetch(bucket=upload_target.bucket, key=upload_target.key)

        # Replay the engine's stdout protocol once (pod logs are only available post-run).
        if on_output_line and stdout:
            for line in stdout.splitlines():
                try:
                    on_output_line(line)
                except Exception:
                    logger.exception("scan_job on_output_line failed name=%s", name)

        artifact_ref = upload_target.ref if upload_target is not None else ""
        if timed_out:
            return ScanJobResult(stdout=stdout, exit_code=124, timed_out=True, artifact_ref=artifact_ref)
        return ScanJobResult(stdout=stdout, exit_code=exit_code, artifact_ref=artifact_ref)

    def _artifact_store(self):
        if self._store is None:
            from components.scanning.application.providers.scan_artifact_store_provider import (
                get_scan_artifact_store,
            )

            self._store = get_scan_artifact_store()
        return self._store

    # ── rendering ──────────────────────────────────────────────────────
    def _job(self, name: str, secret_name: str, spec: ScanJobSpec, upload_target=None):
        from kubernetes import client

        env = [client.V1EnvVar(name="AWS_EC2_METADATA_DISABLED", value="true")]
        env += [client.V1EnvVar(name=k, value=v) for k, v in spec.env.items()]

        container = client.V1Container(
            name="scanner",
            image=spec.image,
            command=list(spec.args),  # fixed argv; no shell
            env=env,
            env_from=(
                [client.V1EnvFromSource(secret_ref=client.V1SecretEnvSource(name=secret_name, optional=True))]
                if spec.secret_env
                else None
            ),
            volume_mounts=[client.V1VolumeMount(name="scratch", mount_path="/tmp")],
            resources=client.V1ResourceRequirements(
                requests={"memory": "256Mi", "cpu": "250m", "ephemeral-storage": "1Gi"},
                limits={"memory": spec.memory_limit or "2Gi", "cpu": "2", "ephemeral-storage": "4Gi"},
            ),
            security_context=client.V1SecurityContext(
                allow_privilege_escalation=False,
                read_only_root_filesystem=True,
                capabilities=client.V1Capabilities(drop=["ALL"]),
            ),
        )
        containers = [container]
        if upload_target is not None:
            containers.append(self._uploader_container(spec, upload_target))

        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            automount_service_account_token=False,
            runtime_class_name=_RUNTIME_CLASS,
            security_context=client.V1PodSecurityContext(
                run_as_non_root=True,
                run_as_user=spec.run_as_user or 10001,
                fs_group=spec.run_as_user or 10001,
                seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
            ),
            containers=containers,
            volumes=[client.V1Volume(name="scratch", empty_dir=client.V1EmptyDirVolumeSource(size_limit="4Gi"))],
        )
        labels = {"app.kubernetes.io/part-of": "autosec-scan", "autosec.dev/scan-source": spec.source}
        return client.V1Job(
            metadata=client.V1ObjectMeta(name=name, labels=labels),
            spec=client.V1JobSpec(
                backoff_limit=0,
                ttl_seconds_after_finished=600,
                active_deadline_seconds=spec.timeout_seconds,
                template=client.V1PodTemplateSpec(metadata=client.V1ObjectMeta(labels=labels), spec=pod_spec),
            ),
        )

    def _uploader_container(self, spec: ScanJobSpec, upload_target):
        """The co-container that ships the engine's result document to object storage.

        WHY a co-container instead of having the engine upload (ADR 0022 D3): the pinned
        engine images have no common uploader — ``aquasec/trivy`` carries only busybox
        ``wget``, which cannot perform an HTTP PUT at all. Making the engines upload would
        mean either a per-engine transport (the thing this design exists to avoid) or
        rebuilding the official Trivy/Prowler images, reversing the "official image +
        native CLI" principle. So the engine keeps writing a file — which all three
        already do — and OUR pinned uploader ships it.

        It holds NO object-storage credentials: it gets a presigned PUT URL good for one
        key. The scan tier is untrusted; a capability is the right thing to hand it.

        Coordination is a sentinel file on the shared scratch volume, and the failure
        semantics fall out of Kubernetes for free: a Job pod succeeds only when EVERY
        container exits 0, so an upload that fails fails the Job, which the adapter's
        existing fail-loud path turns into a FAILED ScanRun. Upload failure is never a
        silent skip (ADR 0022 D4).
        """
        from kubernetes import client

        return client.V1Container(
            name="artifact-uploader",
            image=_UPLOADER_IMAGE,
            command=["/bin/sh", "-c", _UPLOADER_SCRIPT],
            env=[
                client.V1EnvVar(name="ARTIFACT_PATH", value=spec.artifact_path),
                client.V1EnvVar(name="SENTINEL_PATH", value=_SENTINEL_PATH),
                client.V1EnvVar(name="UPLOAD_URL", value=upload_target.url),
                # Outlive the engine: the uploader must still be waiting when a slow scan
                # finishes, or it would exit early and lose the artifact.
                client.V1EnvVar(name="WAIT_SECONDS", value=str(spec.timeout_seconds + 60)),
            ],
            volume_mounts=[client.V1VolumeMount(name="scratch", mount_path="/tmp")],
            resources=client.V1ResourceRequirements(
                requests={"memory": "32Mi", "cpu": "50m"},
                limits={"memory": "256Mi", "cpu": "500m"},
            ),
            security_context=client.V1SecurityContext(
                allow_privilege_escalation=False,
                read_only_root_filesystem=True,
                capabilities=client.V1Capabilities(drop=["ALL"]),
            ),
        )

    # ── lifecycle helpers ──────────────────────────────────────────────
    def _create_secret(self, core, name: str, data: dict[str, str]) -> None:
        if not data:
            return
        from kubernetes import client

        core.create_namespaced_secret(
            _NAMESPACE,
            client.V1Secret(metadata=client.V1ObjectMeta(name=name), string_data=dict(data)),
        )

    def _wait(self, batch, name: str, timeout: int, on_progress) -> bool:
        deadline = timeout + 30
        waited = 0
        while waited < deadline:
            job = batch.read_namespaced_job_status(name, _NAMESPACE)
            status = job.status
            if status.succeeded or status.failed:
                return False
            if on_progress:
                on_progress(min(90.0, 15.0 + waited))
            time.sleep(_POLL_SECONDS)
            waited += _POLL_SECONDS
        logger.warning("scan_job timed out name=%s", name)
        return True

    def _collect(self, batch, core, name: str) -> tuple[str, int]:
        """Return (raw stdout, exit code). A retrieval failure is a FAILED run.

        Retrieval is a distinct failure from the engine's own exit status: the Job can
        succeed while we fail to read what it produced. Reporting that as ("" , 0) would
        hand the adapter an empty-but-successful scan — a COMPLETED run with zero
        findings over output we never actually saw. ``_EXIT_OUTPUT_UNAVAILABLE`` makes
        it fail loud at the earliest, most accurate point instead.
        """
        pods = core.list_namespaced_pod(_NAMESPACE, label_selector=f"job-name={name}")
        if not pods.items:
            logger.error("scan_job pod missing — cannot retrieve output name=%s", name)
            return "", _EXIT_OUTPUT_UNAVAILABLE
        pod = pods.items[0]
        try:
            # _preload_content=False → get the RAW log bytes. With the default (True) the
            # client sees valid-JSON log content, deserializes it to a Python object and
            # str()s it back — corrupting the scanner's JSON into single-quote dict-repr that
            # json.loads then rejects (every scan silently returns 0 findings). Read raw.
            resp = core.read_namespaced_pod_log(
                pod.metadata.name, _NAMESPACE, container="scanner", _preload_content=False
            )
            logs = resp.data.decode("utf-8")
        except Exception:
            logger.exception("scan_job log read failed name=%s", name)
            return "", _EXIT_OUTPUT_UNAVAILABLE
        job = batch.read_namespaced_job_status(name, _NAMESPACE)
        exit_code = 0 if (job.status.succeeded or 0) else 1
        return logs or "", exit_code

    def _delete_secret(self, core, name: str) -> None:
        try:
            core.delete_namespaced_secret(name, _NAMESPACE)
        except Exception:
            pass

    def _delete_job(self, batch, name: str) -> None:
        try:
            from kubernetes import client

            batch.delete_namespaced_job(
                name, _NAMESPACE, propagation_policy="Background", body=client.V1DeleteOptions()
            )
        except Exception:
            pass
