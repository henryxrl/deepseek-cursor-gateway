from __future__ import annotations

import email.utils
import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from urllib.error import HTTPError, URLError

from .logging import LOG


RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})


class RequestStartSmoother:
    """Optional token-bucket rate limiter that smooths how fast requests *start*.

    This is NOT the primary limiter — ``upstream_max_inflight`` is.  The
    smoother only adds a small delay before acquiring an upstream slot.
    It is disabled by default (rate_per_minute=0 or burst=0).

    All waiting happens *outside* the semaphore so other Cursor requests
    are not blocked.
    """

    def __init__(self, rate_per_minute: float, burst: int) -> None:
        self._rate = rate_per_minute / 60.0 if rate_per_minute > 0 else 0.0
        self._capacity = max(burst, 0)
        self._enabled = self._rate > 0 and self._capacity > 0
        self._tokens = float(self._capacity) if self._enabled else 0.0
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def wait_if_needed(self) -> None:
        """Block until a token is available, then consume it."""
        if not self._enabled:
            return

        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self._last_refill)
                self._tokens = min(
                    self._capacity,
                    self._tokens + elapsed * self._rate,
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait = (1.0 - self._tokens) / self._rate

            # Sleep outside the lock, then loop and consume a real token.
            time.sleep(wait)


class UpstreamQueueTimeout(Exception):
    """Raised when a Cursor request waits too long for an upstream DeepSeek slot."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(
            "Timed out waiting for an upstream DeepSeek slot "
            f"after {timeout_seconds:.0f}s. "
            "Reduce Cursor concurrency or increase upstream_max_inflight."
        )


@dataclass(frozen=True)
class RetryConfig:
    enabled: bool = True
    max_attempts: int = 3
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 30.0
    jitter_seconds: float = 1.0
    respect_retry_after: bool = True
    cooldown_on_429: bool = True


class TrafficController:
    """Controls upstream concurrency and retry/backoff for DeepSeek requests.

    DeepSeek enforces account-level concurrency (500 for Pro, 2500 for Flash).
    The gateway's limit is much lower, designed to keep Cursor agent mode
    from overwhelming a single session with parallel thinking requests.
    """

    def __init__(
        self,
        max_inflight: int,
        queue_timeout_seconds: float,
        retry_config: RetryConfig | None = None,
        smoother: RequestStartSmoother | None = None,
    ) -> None:
        self._max_inflight = max_inflight
        self._queue_timeout = queue_timeout_seconds
        self._enabled = max_inflight > 0
        self._semaphore = (
            threading.BoundedSemaphore(max_inflight) if self._enabled else None
        )
        self._retry = retry_config or RetryConfig(enabled=False)
        self._smoother = smoother
        self._active = 0
        self._lock = threading.Lock()
        self._cooldown_until: float = 0.0

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    @property
    def max_inflight(self) -> int:
        return self._max_inflight

    @property
    def enabled(self) -> bool:
        return self._enabled

    # -- internal helpers -------------------------------------------------

    def _acquire_slot(self) -> None:
        if self._semaphore is None:
            return
        acquired = self._semaphore.acquire(timeout=self._queue_timeout)
        if not acquired:
            raise UpstreamQueueTimeout(self._queue_timeout)
        with self._lock:
            self._active += 1

    def _release_slot(self) -> None:
        if self._semaphore is None:
            return
        self._semaphore.release()
        with self._lock:
            self._active -= 1

    def _wait_cooldown(self) -> None:
        while True:
            with self._lock:
                remaining = self._cooldown_until - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(remaining)

    def _set_cooldown(self, delay: float) -> None:
        deadline = time.monotonic() + delay
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, deadline)

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """Return True for transient upstream errors that should be retried."""
        if isinstance(exc, HTTPError):
            return exc.code in RETRYABLE_STATUSES
        return isinstance(exc, URLError)

    def _compute_delay(self, exc: Exception, attempt: int) -> float:
        """Compute retry delay with backoff, Retry-After, jitter, and cap."""
        # Try Retry-After header first
        retry_after: float | None = None
        if self._retry.respect_retry_after and isinstance(exc, HTTPError):
            ra_header = (
                exc.headers.get("Retry-After", "") if hasattr(exc, "headers") else ""
            )
            if ra_header:
                retry_after = _parse_retry_after(str(ra_header))

        if retry_after is not None:
            base = retry_after
        else:
            base = self._retry.base_delay_seconds * (2**attempt)

        jitter = random.uniform(0, self._retry.jitter_seconds)
        return min(base + jitter, self._retry.max_delay_seconds)

    # -- public API -------------------------------------------------------

    @contextmanager
    def open_upstream(
        self,
        make_request: Callable[[], Any] | None = None,
    ) -> Iterator[Any]:
        """Acquire an upstream slot and execute ``make_request()`` with retry.

        If ``make_request`` is ``None`` (backward-compat / test use), the old
        slot-only behaviour is used.

        The slot is held for the entire upstream lifecycle (successful
        urlopen + response consumption).  Between retry attempts the slot is
        released so that other Cursor requests are not blocked by local
        sleep / backoff.

        Raises ``UpstreamQueueTimeout`` if no slot becomes available, and
        re-raises the last upstream exception if all retries are exhausted.
        """
        if make_request is None:
            # Backward-compatible slot-only mode (tests, disabled config).
            if not self._enabled:
                yield None
                return
            if self._smoother is not None:
                self._smoother.wait_if_needed()
            self._acquire_slot()
            try:
                yield None
            finally:
                self._release_slot()
            return

        total_attempts = max(1, self._retry.max_attempts) if self._retry.enabled else 1
        max_retries = total_attempts - 1
        last_exc: Exception | None = None

        for attempt in range(total_attempts):
            # Wait out any global 429 cooldown before trying
            if self._retry.cooldown_on_429:
                self._wait_cooldown()

            if self._smoother is not None:
                self._smoother.wait_if_needed()

            self._acquire_slot()
            try:
                response = make_request()
            except Exception as exc:
                self._release_slot()
                last_exc = exc

                if not self._retry.enabled:
                    raise
                if not self._should_retry(exc):
                    raise

                delay = self._compute_delay(exc, attempt)

                # Update global cooldown on 429
                if self._retry.cooldown_on_429 and _is_429(exc):
                    self._set_cooldown(delay)

                if attempt >= total_attempts - 1:
                    raise

                # Log retry event
                LOG.warning(
                    "retry attempt=%s/%s delay_ms=%s",
                    attempt + 1,
                    max_retries,
                    round(delay * 1000),
                )
                time.sleep(delay)
                continue

            # Success — yield response while holding the slot
            try:
                yield response
            finally:
                self._release_slot()
            return

        # Should not reach here, but safety net
        if last_exc is not None:
            raise last_exc


# -- helpers -------------------------------------------------------------


def _parse_retry_after(header: str) -> float | None:
    """Parse Retry-After header as delta-seconds or HTTP-date."""
    stripped = header.strip()
    if not stripped:
        return None
    # Try delta-seconds
    try:
        return float(stripped)
    except ValueError:
        pass
    # Try HTTP-date
    try:
        parsed = email.utils.parsedate_to_datetime(stripped)
        if parsed is not None:
            return max(0.0, parsed.timestamp() - time.time())
    except (ValueError, TypeError):
        pass
    return None


def _is_429(exc: Exception) -> bool:
    return isinstance(exc, HTTPError) and exc.code == 429
