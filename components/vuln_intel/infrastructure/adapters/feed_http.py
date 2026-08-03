"""Bounded HTTP + gunzip helpers for threat-intel feed pulls (supply-chain hardening).

A security tool ingesting third-party feeds must never let an oversized body or a
gzip-bomb OOM the worker. ``httpx`` has NO default size limit, so we stream the response
and cap the raw bytes read; and we decompress gzip incrementally with a ceiling on the
inflated size. Both caps raise ``MalformedFeedError`` (a versioned, reproducible snapshot
can't be built from an over-limit pull) so the ingest fails loudly instead of exhausting RAM.
"""

from __future__ import annotations

import zlib

import httpx

from components.vuln_intel.domain.errors import MalformedFeedError

# Sane ceilings: EPSS gz is ~3MB (raw) → ~20MB (inflated); KEV JSON ~5MB. These block a
# bomb / runaway body while leaving generous headroom for feed growth.
MAX_RAW_BYTES = 100 * 1024 * 1024  # 100 MB on the wire
MAX_DECOMPRESSED_BYTES = 500 * 1024 * 1024  # 500 MB inflated
HTTP_TIMEOUT = 60.0

_GUNZIP_CHUNK = 1 << 20  # 1 MB output per decompress step


def download_capped(url: str, *, client: httpx.Client | None = None, max_bytes: int = MAX_RAW_BYTES) -> bytes:
    """Stream ``url`` into memory, aborting if the body exceeds ``max_bytes`` (no unbounded
    ``resp.content``). Reuses an injected client (tests) or opens a timeout-bounded one."""
    if client is not None:
        return _stream_capped(client, url, max_bytes)
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as owned:
        return _stream_capped(owned, url, max_bytes)


def _stream_capped(client: httpx.Client, url: str, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise MalformedFeedError(f"feed body exceeded {max_bytes} bytes: {url}")
            chunks.append(chunk)
    return b"".join(chunks)


def gunzip_capped(raw: bytes, *, max_bytes: int = MAX_DECOMPRESSED_BYTES) -> bytes:
    """Inflate gzip ``raw`` incrementally, aborting if the output exceeds ``max_bytes``
    (gzip-bomb guard). Uses zlib with a gzip window so the ceiling is enforced mid-inflate,
    not after a full decompress into RAM."""
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)  # 16 = gzip header
    out = bytearray()
    data = raw
    while True:
        piece = decompressor.decompress(data, _GUNZIP_CHUNK)
        if not piece and not decompressor.unconsumed_tail:
            break
        out.extend(piece)
        if len(out) > max_bytes:
            raise MalformedFeedError(f"decompressed feed exceeded {max_bytes} bytes")
        data = decompressor.unconsumed_tail
    out.extend(decompressor.flush())
    if len(out) > max_bytes:
        raise MalformedFeedError(f"decompressed feed exceeded {max_bytes} bytes")
    return bytes(out)
