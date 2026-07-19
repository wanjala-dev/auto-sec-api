"""Unit tests for upload_tasks._local_file_path — pure fakes, no DB/storage."""

from __future__ import annotations

import os

from components.shared_platform.infrastructure.tasks.upload_tasks import (
    _local_file_path,
)


class _LocalFieldFile:
    """Mimics a FieldFile on local storage: .path resolves."""

    def __init__(self, path: str, name: str = "doc.pdf"):
        self._path = path
        self.name = name

    @property
    def path(self):
        return self._path


class _RemoteFieldFile:
    """Mimics a FieldFile on S3 storage: .path raises, bytes stream via chunks."""

    def __init__(self, payload: bytes, name: str = "uploads/x/report.pdf"):
        self._payload = payload
        self.name = name
        self.opened = False
        self.closed = False

    @property
    def path(self):
        raise NotImplementedError("This backend doesn't support absolute paths.")

    def open(self, mode="rb"):
        self.opened = True
        return self

    def close(self):
        self.closed = True

    def chunks(self, chunk_size=None):
        yield self._payload


class _Instance:
    def __init__(self, field_file):
        self.file = field_file


class TestLocalFilePath:
    def test_local_storage_yields_real_path(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"%PDF-1.4 local")
        instance = _Instance(_LocalFieldFile(str(p)))

        with _local_file_path(instance) as path:
            assert path == str(p)
            assert os.path.exists(path)
        # Real files are NOT cleaned up — they belong to the storage.
        assert os.path.exists(str(p))

    def test_remote_storage_materializes_temp_file_and_cleans_up(self):
        payload = b"%PDF-1.4 remote bytes"
        remote = _RemoteFieldFile(payload, name="uploads/abc/q3-report.pdf")
        instance = _Instance(remote)

        with _local_file_path(instance) as path:
            assert os.path.exists(path)
            # Extension preserved so loaders detect the format.
            assert path.endswith(".pdf")
            with open(path, "rb") as fh:
                assert fh.read() == payload
            assert remote.opened is True
            assert remote.closed is True
            kept = path
        # Temp file removed after the context exits.
        assert not os.path.exists(kept)

    def test_remote_cleanup_happens_even_when_consumer_raises(self):
        remote = _RemoteFieldFile(b"data", name="sheet.xlsx")
        instance = _Instance(remote)
        kept = None
        try:
            with _local_file_path(instance) as path:
                kept = path
                raise RuntimeError("loader exploded")
        except RuntimeError:
            pass
        assert kept is not None
        assert not os.path.exists(kept)
