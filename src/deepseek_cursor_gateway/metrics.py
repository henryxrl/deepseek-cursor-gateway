from __future__ import annotations

import threading


class _DurationStats:
    __slots__ = ("_count", "_lock", "_sum")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sum = 0.0
        self._count = 0

    def observe(self, seconds: float) -> None:
        if seconds < 0:
            return
        with self._lock:
            self._sum += seconds
            self._count += 1

    def snapshot(self) -> tuple[float, int]:
        with self._lock:
            return self._sum, self._count


class GatewayMetrics:
    """Thread-safe Prometheus-text-format metrics collector.

    This module produces a ``/metrics`` endpoint payload without requiring
    any third-party Prometheus client library — the format is simple enough
    to generate with standard Python.
    """

    _instance: GatewayMetrics | None = None
    _instance_lock: threading.Lock = threading.Lock()

    @classmethod
    def install(cls, instance: "GatewayMetrics") -> None:
        """Bind the process-wide metrics instance used by rate_limiter and reasoning_store."""
        with cls._instance_lock:
            cls._instance = instance

    @classmethod
    def global_instance(cls) -> GatewayMetrics:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        """Clear the process-wide singleton (unit tests only)."""
        with cls._instance_lock:
            cls._instance = None

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Counters
        self._requests_total: dict[str, int] = {}  # key: "path|status"
        self._retry_attempts: int = 0
        self._cooldown_count: int = 0
        self._reasoning_cache_hits: int = 0
        self._reasoning_cache_misses: int = 0
        self._upstream_errors: dict[str, int] = {}  # key: "status_code"
        self._ocr_cache_hits: int = 0
        self._ocr_cache_misses: int = 0
        self._recovery_count: int = 0
        self._missing_reasoning_count: int = 0

        # Gauges
        self._upstream_active: int = 0

        # Summaries
        self._upstream_duration = _DurationStats()
        self._queue_wait_duration = _DurationStats()
        self._ocr_duration = _DurationStats()

    # -- recorders ---------------------------------------------------------

    def record_request(self, path: str, status: int) -> None:
        key = f"{path}|{status}"
        with self._lock:
            self._requests_total[key] = self._requests_total.get(key, 0) + 1

    def record_retry(self) -> None:
        with self._lock:
            self._retry_attempts += 1

    def record_cooldown(self) -> None:
        with self._lock:
            self._cooldown_count += 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self._reasoning_cache_hits += 1

    def record_cache_miss(self) -> None:
        with self._lock:
            self._reasoning_cache_misses += 1

    def record_upstream_error(self, status: int) -> None:
        key = str(status)
        with self._lock:
            self._upstream_errors[key] = self._upstream_errors.get(key, 0) + 1

    def record_ocr_cache_hit(self) -> None:
        with self._lock:
            self._ocr_cache_hits += 1

    def record_ocr_cache_miss(self) -> None:
        with self._lock:
            self._ocr_cache_misses += 1

    def record_recovery(self, count: int = 1) -> None:
        if count <= 0:
            return
        with self._lock:
            self._recovery_count += count

    def record_missing_reasoning(self, count: int = 1) -> None:
        if count <= 0:
            return
        with self._lock:
            self._missing_reasoning_count += count

    def set_upstream_active(self, active: int) -> None:
        with self._lock:
            self._upstream_active = max(0, active)

    def observe_upstream_duration(self, seconds: float) -> None:
        self._upstream_duration.observe(seconds)

    def observe_queue_wait(self, seconds: float) -> None:
        self._queue_wait_duration.observe(seconds)

    def observe_ocr_duration(self, seconds: float) -> None:
        self._ocr_duration.observe(seconds)

    # -- scrape ------------------------------------------------------------

    @staticmethod
    def _render_summary(name: str, help_text: str, stats: _DurationStats) -> list[str]:
        total, count = stats.snapshot()
        return [
            f"# HELP {name} {help_text}",
            f"# TYPE {name} summary",
            f"{name}_sum {total:.6f}",
            f"{name}_count {count}",
        ]

    def scrape(self) -> str:
        """Render all metrics in Prometheus text format (one line per sample)."""
        with self._lock:
            parts: list[str] = []
            parts.append(
                "# HELP gateway_requests_total Total requests by path and status"
            )
            parts.append("# TYPE gateway_requests_total counter")
            for key, count in sorted(self._requests_total.items()):
                path, status = key.split("|")
                parts.append(
                    f'gateway_requests_total{{path="{path}",status="{status}"}} {count}'
                )

            parts.append("")
            parts.append(
                "# HELP gateway_retry_attempts_total Total upstream retry attempts"
            )
            parts.append("# TYPE gateway_retry_attempts_total counter")
            parts.append(f"gateway_retry_attempts_total {self._retry_attempts}")

            parts.append("")
            parts.append(
                "# HELP gateway_cooldown_total Total global cooldown events after 429"
            )
            parts.append("# TYPE gateway_cooldown_total counter")
            parts.append(f"gateway_cooldown_total {self._cooldown_count}")

            total_cache_ops = self._reasoning_cache_hits + self._reasoning_cache_misses
            hit_ratio = (
                self._reasoning_cache_hits / total_cache_ops
                if total_cache_ops > 0
                else 0.0
            )
            parts.append("")
            parts.append(
                "# HELP gateway_reasoning_cache_hits_total Total reasoning cache hits"
            )
            parts.append("# TYPE gateway_reasoning_cache_hits_total counter")
            parts.append(
                f"gateway_reasoning_cache_hits_total {self._reasoning_cache_hits}"
            )
            parts.append("")
            parts.append(
                "# HELP gateway_reasoning_cache_misses_total Total reasoning cache misses"
            )
            parts.append("# TYPE gateway_reasoning_cache_misses_total counter")
            parts.append(
                f"gateway_reasoning_cache_misses_total {self._reasoning_cache_misses}"
            )
            parts.append("")
            parts.append(
                "# HELP gateway_reasoning_cache_hit_ratio Hit ratio of reasoning cache"
            )
            parts.append("# TYPE gateway_reasoning_cache_hit_ratio gauge")
            parts.append(f"gateway_reasoning_cache_hit_ratio {hit_ratio:.4f}")

            if self._upstream_errors:
                parts.append("")
                parts.append(
                    "# HELP gateway_upstream_errors_total Upstream errors by HTTP status"
                )
                parts.append("# TYPE gateway_upstream_errors_total counter")
                for status, count in sorted(self._upstream_errors.items()):
                    parts.append(
                        f'gateway_upstream_errors_total{{status="{status}"}} {count}'
                    )

            parts.append("")
            parts.append("# HELP gateway_ocr_cache_hits_total Total OCR cache hits")
            parts.append("# TYPE gateway_ocr_cache_hits_total counter")
            parts.append(f"gateway_ocr_cache_hits_total {self._ocr_cache_hits}")

            parts.append("")
            parts.append("# HELP gateway_ocr_cache_misses_total Total OCR cache misses")
            parts.append("# TYPE gateway_ocr_cache_misses_total counter")
            parts.append(f"gateway_ocr_cache_misses_total {self._ocr_cache_misses}")

            parts.append("")
            parts.append(
                "# HELP gateway_recovery_total Total reasoning recovery events"
            )
            parts.append("# TYPE gateway_recovery_total counter")
            parts.append(f"gateway_recovery_total {self._recovery_count}")

            parts.append("")
            parts.append(
                "# HELP gateway_missing_reasoning_total Total missing reasoning occurrences"
            )
            parts.append("# TYPE gateway_missing_reasoning_total counter")
            parts.append(
                f"gateway_missing_reasoning_total {self._missing_reasoning_count}"
            )

            parts.append("")
            parts.append(
                "# HELP gateway_upstream_active_requests Active upstream requests"
            )
            parts.append("# TYPE gateway_upstream_active_requests gauge")
            parts.append(f"gateway_upstream_active_requests {self._upstream_active}")

        parts.extend(
            self._render_summary(
                "gateway_upstream_request_duration_seconds",
                "Upstream request duration in seconds",
                self._upstream_duration,
            )
        )
        parts.append("")
        parts.extend(
            self._render_summary(
                "gateway_queue_wait_duration_seconds",
                "Queue wait duration before acquiring upstream slot",
                self._queue_wait_duration,
            )
        )
        parts.append("")
        parts.extend(
            self._render_summary(
                "gateway_ocr_duration_seconds",
                "OCR vision call duration in seconds",
                self._ocr_duration,
            )
        )
        parts.append("")
        return "\n".join(parts)


def wire_gateway_metrics(server: object) -> GatewayMetrics:
    """Attach a single metrics instance to a gateway server and install it globally."""
    metrics = GatewayMetrics()
    GatewayMetrics.install(metrics)
    setattr(server, "metrics", metrics)
    return metrics
