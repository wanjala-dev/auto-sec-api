"""Isolated detector execution with per-detector timeout and failure containment.

Each detector runs inside a timeout guard so one slow or broken detector
cannot kill the entire AI teammate cycle. Failures are logged and returned
as error summaries — they never propagate to the caller.

This replaces the inline `for detector in self.detectors` loop that was
inside the legacy OrchestratorAgent (now retired). Called from
`application/services/detector_cycle.py`.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default per-detector timeout (seconds). Can be overridden per workspace.
DEFAULT_DETECTOR_TIMEOUT = 30


@dataclass
class DetectorResult:
    """Outcome of running a single detector."""

    slug: str
    results: list[Any] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""
    duration_ms: int = 0


def run_detector_isolated(
    detector,
    context,
    *,
    timeout_seconds: float = DEFAULT_DETECTOR_TIMEOUT,
) -> DetectorResult:
    """Execute a single detector with timeout + error isolation.

    Args:
        detector: A detector instance with ``slug``, ``should_run()``,
                  ``gather_signals()``, and ``execute()`` methods.
        context: The DetectorContext to pass to the detector.
        timeout_seconds: Max wall-clock seconds for this detector.

    Returns:
        DetectorResult with results/signals on success, or error details on failure.
        Never raises.
    """
    slug = getattr(detector, "slug", str(detector))
    start = time.monotonic()

    # Check should_run first (cheap, no timeout needed)
    try:
        if not detector.should_run(context):
            return DetectorResult(
                slug=slug,
                skipped=True,
                skip_reason="should_run returned False",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
    except Exception as exc:
        return DetectorResult(
            slug=slug,
            skipped=True,
            skip_reason=f"should_run raised: {exc}",
            error=str(exc),
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    # Run gather_signals + execute inside a thread with timeout
    result = DetectorResult(slug=slug)

    def _run():
        # Gather signals
        try:
            sigs = detector.gather_signals(context)
            if sigs:
                result.signals.extend(s.to_dict() for s in sigs)
        except AttributeError:
            pass  # gather_signals not implemented
        except Exception as exc:
            logger.warning("detector.gather_signals failed slug=%s: %s", slug, exc)

        # Execute
        result.results = list(detector.execute(context))

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run)
        try:
            future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            result.error = f"Timed out after {timeout_seconds}s"
            result.skipped = True
            result.skip_reason = "timeout"
            logger.error("detector.timeout slug=%s timeout=%ss", slug, timeout_seconds)
        except Exception as exc:
            result.error = str(exc)
            logger.exception("detector.execute failed slug=%s: %s", slug, exc)

    result.duration_ms = int((time.monotonic() - start) * 1000)
    return result


def run_all_detectors(
    detectors: list,
    context,
    *,
    timeout_per_detector: float = DEFAULT_DETECTOR_TIMEOUT,
    max_parallel: int = 4,
    cancellation_token=None,
) -> list[DetectorResult]:
    """Run all detectors with per-detector timeout and optional parallelism.

    Args:
        detectors: List of detector instances.
        context: The DetectorContext.
        timeout_per_detector: Max seconds per detector.
        max_parallel: Max concurrent detectors (1 = serial).

    Returns:
        List of DetectorResult, one per detector. Never raises.
    """
    if max_parallel <= 1:
        results = []
        for d in detectors:
            # Check cancellation between detectors
            if cancellation_token and cancellation_token.is_cancelled:
                slug = getattr(d, "slug", str(d))
                results.append(DetectorResult(slug=slug, skipped=True, skip_reason="cancelled"))
                continue
            results.append(
                run_detector_isolated(d, context, timeout_seconds=timeout_per_detector)
            )
        return results

    results: list[DetectorResult] = []
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {
            pool.submit(run_detector_isolated, d, context, timeout_seconds=timeout_per_detector): d
            for d in detectors
        }
        for future in futures:
            try:
                results.append(future.result(timeout=timeout_per_detector + 5))
            except Exception as exc:
                detector = futures[future]
                slug = getattr(detector, "slug", "unknown")
                logger.exception("detector.parallel_error slug=%s: %s", slug, exc)
                results.append(DetectorResult(slug=slug, error=str(exc)))

    return results
