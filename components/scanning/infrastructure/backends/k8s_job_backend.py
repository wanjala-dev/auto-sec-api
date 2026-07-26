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
    ProgressCallback,
    ScanExecutionBackend,
    ScanJobResult,
    ScanJobSpec,
)

logger = logging.getLogger(__name__)

_NAMESPACE = os.environ.get("SCAN_JOB_NAMESPACE", "autosec")
_RUNTIME_CLASS = os.environ.get("SCAN_JOB_RUNTIME_CLASS") or None  # e.g. "gvisor" when available
_POLL_SECONDS = 3


class K8sJobBackend(ScanExecutionBackend):
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

        self._create_secret(core, secret_name, spec.secret_env)
        try:
            batch.create_namespaced_job(_NAMESPACE, self._job(name, secret_name, spec))
            timed_out = self._wait(batch, name, spec.timeout_seconds, on_progress)
            stdout, exit_code = self._collect(batch, core, name)
        finally:
            self._delete_secret(core, secret_name)
            self._delete_job(batch, name)

        # Replay the engine's stdout protocol once (pod logs are only available post-run).
        if on_output_line and stdout:
            for line in stdout.splitlines():
                try:
                    on_output_line(line)
                except Exception:
                    logger.exception("scan_job on_output_line failed name=%s", name)

        if timed_out:
            return ScanJobResult(stdout=stdout, exit_code=124, timed_out=True)
        return ScanJobResult(stdout=stdout, exit_code=exit_code)

    # ── rendering ──────────────────────────────────────────────────────
    def _job(self, name: str, secret_name: str, spec: ScanJobSpec):
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
                limits={"memory": "2Gi", "cpu": "2", "ephemeral-storage": "4Gi"},
            ),
            security_context=client.V1SecurityContext(
                allow_privilege_escalation=False,
                read_only_root_filesystem=True,
                capabilities=client.V1Capabilities(drop=["ALL"]),
            ),
        )
        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            automount_service_account_token=False,
            runtime_class_name=_RUNTIME_CLASS,
            security_context=client.V1PodSecurityContext(
                run_as_non_root=True,
                run_as_user=10001,
                fs_group=10001,
                seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
            ),
            containers=[container],
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
        pods = core.list_namespaced_pod(_NAMESPACE, label_selector=f"job-name={name}")
        if not pods.items:
            return "", 1
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
            logs = ""
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
