"""Observability endpoints, metrics, probes, readiness, and request manifests."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from deepseek_cursor_gateway.config import GatewayConfig
from deepseek_cursor_gateway.metrics import GatewayMetrics, wire_gateway_metrics
from deepseek_cursor_gateway.rate_limiter import RetryConfig, TrafficController
from deepseek_cursor_gateway.reasoning_store import ReasoningStore
from deepseek_cursor_gateway.server import (
    DeepSeekGatewayHandler,
    DeepSeekGatewayServer,
    assess_gateway_readiness,
    probe_upstream,
    probe_upstream_reachable,
)
from deepseek_cursor_gateway.trace import TraceWriter


class _PlainFakeUpstream(BaseHTTPRequestHandler):
    requests: list[dict] = []
    response: dict = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    def log_message(self, *_args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        _PlainFakeUpstream.requests.append(body)
        payload = json.dumps(_PlainFakeUpstream.response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _Fixture:
    def __init__(self, server: ThreadingHTTPServer) -> None:
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _get(url: str) -> tuple[int, str]:
    with urlopen(url, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


def _get_json(url: str, *, allow_error: bool = False) -> tuple[int, dict]:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if not allow_error:
            raise
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _start_gateway(
    upstream_url: str,
    store: ReasoningStore,
    *,
    trace_dir: Path | None = None,
    **config_overrides: object,
) -> _Fixture:
    GatewayMetrics.reset_for_tests()
    gateway = DeepSeekGatewayServer(("127.0.0.1", 0), DeepSeekGatewayHandler)
    gateway.config = GatewayConfig(
        upstream_base_url=upstream_url,
        upstream_model="deepseek-v4-pro",
        vision_api_key="sk-vision-secret",
        ngrok=False,
        verbose=False,
        trace_dir=trace_dir,
        **config_overrides,
    )
    gateway.reasoning_store = store
    gateway.started_at = time.monotonic()
    gateway.vision_ready = True
    gateway.vision_warmup_state = "not_applicable"
    wire_gateway_metrics(gateway)
    gateway.traffic_controller = TrafficController(
        max_inflight=2,
        queue_timeout_seconds=300,
        retry_config=RetryConfig(enabled=False),
    )
    gateway.trace_writer = (
        TraceWriter(trace_dir) if trace_dir is not None else None
    )
    gateway.ocr_cache = None
    return _Fixture(gateway)


class ProbeUpstreamTests(unittest.TestCase):
    def tearDown(self) -> None:
        GatewayMetrics.reset_for_tests()

    @mock.patch("deepseek_cursor_gateway.server.urlopen")
    def test_probe_uses_models_path_when_base_url_ends_with_v1(self, urlopen_mock) -> None:
        urlopen_mock.return_value = BytesIO(b"{}")
        result = probe_upstream("https://api.example.com/v1")
        self.assertTrue(result.reachable)
        self.assertEqual(result.probe_url, "https://api.example.com/v1/models")
        self.assertEqual(result.probe_status, 200)
        self.assertIsNone(result.probe_error_type)

    @mock.patch("deepseek_cursor_gateway.server.urlopen")
    def test_probe_treats_401_as_reachable(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = HTTPError(
            "https://api.example.com/v1/models",
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b""),
        )
        result = probe_upstream("https://api.example.com")
        self.assertTrue(result.reachable)
        self.assertEqual(result.probe_status, 401)
        self.assertEqual(result.probe_error_type, "http_error")

    @mock.patch("deepseek_cursor_gateway.server.urlopen")
    def test_probe_treats_503_as_unreachable(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = HTTPError(
            "https://api.example.com/v1/models",
            503,
            "Unavailable",
            hdrs=None,
            fp=BytesIO(b""),
        )
        result = probe_upstream("https://api.example.com")
        self.assertFalse(result.reachable)
        self.assertEqual(result.probe_status, 503)
        self.assertEqual(result.probe_error_type, "http_error")

    def test_probe_reachable_wrapper(self) -> None:
        with mock.patch(
            "deepseek_cursor_gateway.server.probe_upstream",
            return_value=SimpleNamespace(reachable=True),
        ):
            self.assertTrue(probe_upstream_reachable("https://api.example.com"))


class MetricsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        _PlainFakeUpstream.requests = []
        self.upstream = _Fixture(
            ThreadingHTTPServer(("127.0.0.1", 0), _PlainFakeUpstream)
        )
        self.store = ReasoningStore(":memory:")
        self.gateway = _start_gateway(self.upstream.url, self.store)

    def tearDown(self) -> None:
        self.gateway.close()
        self.upstream.close()
        self.store.close()
        GatewayMetrics.reset_for_tests()

    def test_metrics_include_request_retry_and_cache_counters(self) -> None:
        metrics = self.gateway.server.metrics
        metrics.record_request("/v1/chat/completions", 200)
        metrics.record_retry()
        metrics.record_cache_hit()
        metrics.record_cache_miss()
        metrics.record_recovery(2)
        metrics.record_missing_reasoning(3)
        metrics.observe_upstream_duration(0.5)
        metrics.observe_queue_wait(0.1)
        metrics.set_upstream_active(1)

        status, body = _get(f"{self.gateway.url}/metrics")
        self.assertEqual(status, 200)
        self.assertIn('gateway_requests_total{path="/v1/chat/completions",status="200"} 1', body)
        self.assertIn("gateway_retry_attempts_total 1", body)
        self.assertIn("gateway_reasoning_cache_hits_total 1", body)
        self.assertIn("gateway_reasoning_cache_misses_total 1", body)
        self.assertIn("gateway_recovery_total 2", body)
        self.assertIn("gateway_missing_reasoning_total 3", body)
        self.assertIn("gateway_upstream_active_requests 1", body)
        self.assertIn("gateway_upstream_request_duration_seconds_sum 0.500000", body)
        self.assertIn("gateway_queue_wait_duration_seconds_count 1", body)

    def test_global_instance_matches_server_metrics_after_wire(self) -> None:
        metrics = self.gateway.server.metrics
        metrics.record_retry()
        status, body = _get(f"{self.gateway.url}/metrics")
        self.assertEqual(status, 200)
        self.assertIn("gateway_retry_attempts_total 1", body)


class InfoEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        _PlainFakeUpstream.requests = []
        self.upstream = _Fixture(
            ThreadingHTTPServer(("127.0.0.1", 0), _PlainFakeUpstream)
        )
        self.store = ReasoningStore(":memory:")
        self.gateway = _start_gateway(
            self.upstream.url,
            self.store,
            reasoning_content_path=Path("/tmp/secret-reasoning.sqlite3"),
            image_ocr_cache_path=Path("/tmp/secret-ocr.sqlite3"),
        )

    def tearDown(self) -> None:
        self.gateway.close()
        self.upstream.close()
        self.store.close()
        GatewayMetrics.reset_for_tests()

    def test_info_does_not_expose_secrets_or_sensitive_paths(self) -> None:
        status, payload = _get_json(f"{self.gateway.url}/info")
        self.assertEqual(status, 200)
        body = json.dumps(payload)
        self.assertNotIn("sk-vision-secret", body)
        self.assertNotIn("secret-reasoning.sqlite3", body)
        self.assertNotIn("secret-ocr.sqlite3", body)
        self.assertNotIn("api_key", body)
        self.assertIn("upstream", payload)
        self.assertIn("image_handling", payload)


class HealthAndReadyEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ReasoningStore(":memory:")
        self.gateway = _start_gateway("https://api.example.com", self.store)

    def tearDown(self) -> None:
        self.gateway.close()
        self.store.close()
        GatewayMetrics.reset_for_tests()

    @mock.patch("deepseek_cursor_gateway.server.probe_upstream")
    def test_healthz_upstream_probe_returns_diagnostic_fields(self, probe_mock) -> None:
        probe_mock.return_value = SimpleNamespace(
            reachable=True,
            probe_url="https://api.example.com/v1/models",
            probe_status=401,
            probe_error_type="http_error",
        )
        status, payload = _get_json(f"{self.gateway.url}/healthz?upstream=1")
        self.assertEqual(status, 200)
        self.assertTrue(payload["upstream_reachable"])
        self.assertEqual(payload["probe_url"], "https://api.example.com/v1/models")
        self.assertEqual(payload["probe_status"], 401)
        self.assertEqual(payload["probe_error_type"], "http_error")

    def test_readyz_reports_ready_when_dependencies_ok(self) -> None:
        status, payload = _get_json(f"{self.gateway.url}/readyz")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ready"])
        self.assertTrue(payload["checks"]["reasoning_cache"]["ok"])
        self.assertTrue(payload["checks"]["traffic_controller"]["ok"])

    def test_readyz_returns_503_when_reasoning_cache_unavailable(self) -> None:
        with mock.patch.object(
            self.gateway.server.reasoning_store,
            "ping",
            side_effect=OSError("db down"),
        ):
            ready, checks = assess_gateway_readiness(self.gateway.server)
            self.assertFalse(ready)
            self.assertFalse(checks["reasoning_cache"]["ok"])

            status, payload = _get_json(f"{self.gateway.url}/readyz", allow_error=True)
        self.assertEqual(status, 503)
        self.assertFalse(payload["ready"])


class RequestManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        _PlainFakeUpstream.requests = []
        self.upstream = _Fixture(
            ThreadingHTTPServer(("127.0.0.1", 0), _PlainFakeUpstream)
        )
        self.store = ReasoningStore(":memory:")
        self.trace_dir = Path(tempfile.mkdtemp(prefix="dcp-trace-"))
        self.writer = TraceWriter(self.trace_dir)
        self.gateway = _start_gateway(
            self.upstream.url,
            self.store,
            trace_dir=self.trace_dir,
        )
        self.gateway.server.trace_writer = self.writer

    def tearDown(self) -> None:
        self.gateway.close()
        self.upstream.close()
        self.store.close()
        GatewayMetrics.reset_for_tests()

    def test_completed_request_writes_manifest_to_trace(self) -> None:
        request = Request(
            f"{self.gateway.url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "deepseek-v4-pro",
                    "messages": [{"role": "user", "content": "hi"}],
                }
            ).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": "Bearer sk-test",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)

        trace_files = sorted(self.writer.session_dir.glob("request-*.json"))
        deadline = time.monotonic() + 2
        while not trace_files and time.monotonic() < deadline:
            time.sleep(0.01)
            trace_files = sorted(self.writer.session_dir.glob("request-*.json"))
        self.assertTrue(trace_files)
        completion = json.loads(trace_files[0].read_text(encoding="utf-8"))["completion"]
        manifest = completion["manifest"]
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["model"], "deepseek-v4-pro")
        self.assertFalse(manifest["stream"])
        self.assertEqual(manifest["image_count"], 0)
        self.assertEqual(manifest["upstream_status"], 200)
        self.assertIn("elapsed_ms", manifest)

    def test_request_manifest_is_logged(self) -> None:
        with self.assertLogs("deepseek_cursor_gateway", level="INFO") as captured:
            request = Request(
                f"{self.gateway.url}/v1/chat/completions",
                data=json.dumps(
                    {
                        "model": "deepseek-v4-pro",
                        "messages": [{"role": "user", "content": "hi"}],
                    }
                ).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": "Bearer sk-test",
                    "Content-Type": "application/json",
                },
            )
            with urlopen(request, timeout=5):
                pass
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not any(
                "request_manifest" in line for line in captured.output
            ):
                time.sleep(0.01)
        self.assertTrue(any("request_manifest status=completed" in line for line in captured.output))


class RateLimiterMetricsTests(unittest.TestCase):
    def tearDown(self) -> None:
        GatewayMetrics.reset_for_tests()

    def test_queue_wait_and_active_gauge_recorded(self) -> None:
        GatewayMetrics.reset_for_tests()
        metrics = GatewayMetrics()
        GatewayMetrics.install(metrics)
        controller = TrafficController(max_inflight=1, queue_timeout_seconds=5)

        def hold_slot() -> None:
            with controller.open_upstream():
                time.sleep(0.2)

        holder = threading.Thread(target=hold_slot)
        holder.start()
        time.sleep(0.05)
        with controller.open_upstream():
            pass
        holder.join(timeout=2)

        self.assertGreater(metrics._queue_wait_duration.snapshot()[1], 0)
        self.assertEqual(metrics._upstream_active, 0)
        scrape = metrics.scrape()
        self.assertIn("gateway_queue_wait_duration_seconds_count", scrape)
        self.assertIn("gateway_upstream_active_requests 0", scrape)


if __name__ == "__main__":
    unittest.main()
