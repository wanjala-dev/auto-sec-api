"""ScanArtifactStorePort — where a scan's RAW engine output is persisted (ADR 0022 D2).

The seam between "a scan produced bytes" and "those bytes live in object storage".
Shaped to the Application Core's need — *hand the untrusted Job a one-object write
capability, then read the object back from the trusted side* — not to the S3 API.

That shape is the security decision (ADR 0022 D3, as amended). The scan Job is the
**untrusted tier**: it unpacks customer images and parses customer code. It therefore
never receives object-storage credentials. Instead the trusted worker mints a
**presigned PUT URL** scoped to exactly one object key with a short TTL, and the Job's
uploader container can do precisely one thing with it: write that one object. A
compromised scanner gets no bucket, no other workspace's artifacts, no delete.

The read path is deliberately server-side — the trusted worker fetches with its own
credentials over the internal endpoint. That is what keeps this clear of the known
prod presigned-URL bug (the public/internal endpoint split that breaks report/SBOM
downloads): nothing here depends on a URL being reachable from a browser.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactUploadTarget:
    """A one-object write capability handed to an untrusted scan Job.

    ``url`` is consumed INSIDE the cluster by the Job's uploader container, so it is
    minted against the internal endpoint. ``ref`` is the durable "<bucket>/<key>"
    the trusted side later reads and records on the ``ScanRun``.
    """

    url: str
    bucket: str
    key: str

    @property
    def ref(self) -> str:
        return f"{self.bucket}/{self.key}"


class ScanArtifactStorePort(ABC):
    @abstractmethod
    def presign_put(self, *, workspace_id: str, scan_run_id: str, source: str) -> ArtifactUploadTarget:
        """Mint a short-lived, single-object write capability for this scan's raw output."""

    @abstractmethod
    def fetch(self, *, bucket: str, key: str) -> str:
        """Read a stored artifact back (trusted side, own credentials, internal endpoint).

        Raises rather than returning empty when the object is missing or unreadable —
        an artifact we cannot read is an unusable scan, and ADR 0022 D1's invariant is
        that unusable output fails loud rather than becoming "zero findings".
        """
