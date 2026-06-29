from __future__ import annotations

import threading
import time
import unittest
from unittest import mock
from urllib.error import HTTPError

from deepseek_cursor_gateway.rate_limiter import (
    TrafficController,
    RetryConfig,
    RequestStartSmoother,
    UpstreamQueueTimeout,
)


class TrafficControllerTest(unittest.TestCase):

    # -- backward-compatible slot-only mode (make_request=None) -----------

    def test_disabled_when_zero(self):
        tc = TrafficController(max_inflight=0, queue_timeout_seconds=1)
        self.assertFalse(tc.enabled)
        self.assertEqual(tc.max_inflight, 0)
        self.assertEqual(tc.active, 0)

        with tc.open_upstream():
            self.assertEqual(tc.active, 0)
        self.assertEqual(tc.active, 0)

    def test_single_slot_serializes(self):
        tc = TrafficController(max_inflight=1, queue_timeout_seconds=0.5)

        results: list[str] = []
        lock = threading.Lock()

        def worker(label: str, hold_seconds: float) -> None:
            with tc.open_upstream():
                with lock:
                    results.append(f"enter_{label}")
                time.sleep(hold_seconds)
                with lock:
                    results.append(f"exit_{label}")

        t1 = threading.Thread(target=worker, args=("A", 0.15))
        t2 = threading.Thread(target=worker, args=("B", 0.05))

        t1.start()
        time.sleep(0.02)
        t2.start()

        t1.join()
        t2.join()

        self.assertEqual(results, ["enter_A", "exit_A", "enter_B", "exit_B"])

    def test_active_count_reflects_inflight(self):
        tc = TrafficController(max_inflight=2, queue_timeout_seconds=1)

        active_values: list[int] = []
        event = threading.Event()

        def worker(hold_event: threading.Event) -> None:
            with tc.open_upstream():
                active_values.append(tc.active)
                hold_event.wait()

        t1 = threading.Thread(target=worker, args=(event,))
        t2 = threading.Thread(target=worker, args=(event,))

        t1.start()
        time.sleep(0.02)
        t2.start()
        time.sleep(0.05)

        event.set()
        t1.join()
        t2.join()

        self.assertIn(2, active_values)

    def test_queue_timeout_raises(self):
        tc = TrafficController(max_inflight=1, queue_timeout_seconds=0.1)

        hold = threading.Event()

        def holder() -> None:
            with tc.open_upstream():
                hold.wait()

        t = threading.Thread(target=holder)
        t.start()
        time.sleep(0.02)

        with self.assertRaises(UpstreamQueueTimeout) as ctx:
            with tc.open_upstream():
                pass

        self.assertEqual(ctx.exception.timeout_seconds, 0.1)
        hold.set()
        t.join()

    def test_slot_released_on_exception(self):
        tc = TrafficController(max_inflight=1, queue_timeout_seconds=1)

        try:
            with tc.open_upstream():
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass

        self.assertEqual(tc.active, 0)

        with tc.open_upstream():
            self.assertEqual(tc.active, 1)
        self.assertEqual(tc.active, 0)

    def test_max_inflight_allows_concurrency(self):
        tc = TrafficController(max_inflight=5, queue_timeout_seconds=1)

        counter: list[int] = [0]
        lock = threading.Lock()
        barrier = threading.Barrier(5, timeout=2)

        def worker() -> None:
            with tc.open_upstream():
                with lock:
                    counter[0] += 1
                barrier.wait()

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(counter[0], 5)

    # -- retry mode ------------------------------------------------------

    def test_retry_succeeds_after_transient_failure(self):
        tc = TrafficController(
            max_inflight=2,
            queue_timeout_seconds=1,
            retry_config=RetryConfig(
                enabled=True,
                max_attempts=3,
                base_delay_seconds=0.01,
                jitter_seconds=0.0,
                cooldown_on_429=False,
            ),
        )

        calls: list[int] = []

        def make_request() -> str:
            calls.append(1)
            if len(calls) < 3:
                exc = HTTPError("url", 503, "Service Unavailable", {}, mock.Mock())
                raise exc
            return "ok"

        with tc.open_upstream(make_request) as response:
            self.assertEqual(response, "ok")
            self.assertEqual(tc.active, 1)

        self.assertEqual(tc.active, 0)
        self.assertEqual(len(calls), 3)

    def test_retry_exhausted_raises_last_exception(self):
        tc = TrafficController(
            max_inflight=2,
            queue_timeout_seconds=1,
            retry_config=RetryConfig(
                enabled=True,
                max_attempts=2,
                base_delay_seconds=0.01,
                jitter_seconds=0.0,
                cooldown_on_429=False,
            ),
        )

        mock_fp = mock.Mock()
        exc = HTTPError("url", 429, "Too Many Requests", {}, mock_fp)
        calls: list[int] = []

        def make_request() -> str:
            calls.append(1)
            raise exc

        with self.assertRaises(HTTPError) as ctx:
            with tc.open_upstream(make_request):
                pass

        self.assertEqual(ctx.exception.code, 429)
        self.assertEqual(len(calls), 2)
        self.assertEqual(tc.active, 0)

    def test_retry_works_when_concurrency_limit_disabled(self):
        tc = TrafficController(
            max_inflight=0,
            queue_timeout_seconds=1,
            retry_config=RetryConfig(
                enabled=True,
                max_attempts=2,
                base_delay_seconds=0.01,
                jitter_seconds=0.0,
                cooldown_on_429=False,
            ),
        )

        calls: list[int] = []

        def make_request() -> str:
            calls.append(1)
            if len(calls) == 1:
                raise HTTPError("url", 503, "Service Unavailable", {}, mock.Mock())
            return "ok"

        with tc.open_upstream(make_request) as response:
            self.assertEqual(response, "ok")
            self.assertEqual(tc.active, 0)

        self.assertEqual(len(calls), 2)
        self.assertEqual(tc.active, 0)

    def test_non_retryable_error_not_retried(self):
        tc = TrafficController(
            max_inflight=2,
            queue_timeout_seconds=1,
            retry_config=RetryConfig(
                enabled=True,
                max_attempts=3,
                base_delay_seconds=0.01,
                jitter_seconds=0.0,
                cooldown_on_429=False,
            ),
        )

        calls: list[int] = []

        def make_request() -> str:
            calls.append(1)
            raise HTTPError("url", 400, "Bad Request", {}, mock.Mock())

        with self.assertRaises(HTTPError) as ctx:
            with tc.open_upstream(make_request):
                pass

        self.assertEqual(ctx.exception.code, 400)
        self.assertEqual(len(calls), 1)  # no retries

    def test_cooldown_on_429_blocks_future_attempts(self):
        tc = TrafficController(
            max_inflight=2,
            queue_timeout_seconds=1,
            retry_config=RetryConfig(
                enabled=True,
                max_attempts=1,
                base_delay_seconds=0.05,
                jitter_seconds=0.0,
                cooldown_on_429=True,
            ),
        )

        # First request gets 429 → cooldown set

        def fail_with_429() -> str:
            raise HTTPError("url", 429, "Too Many Requests", {}, mock.Mock())

        with (
            mock.patch(
                "deepseek_cursor_gateway.rate_limiter.time.monotonic",
                side_effect=[100.0, 100.0, 100.01, 100.06],
            ),
            mock.patch("deepseek_cursor_gateway.rate_limiter.time.sleep") as sleep_mock,
        ):
            with self.assertRaises(HTTPError):
                with tc.open_upstream(fail_with_429):
                    pass

            # Second request should wait for cooldown (base_delay=0.05s minimal)
            called = []

            def succeed() -> str:
                called.append(1)
                return "ok"

            with tc.open_upstream(succeed) as response:
                self.assertEqual(response, "ok")

        self.assertEqual(len(called), 1)
        sleep_mock.assert_called_once()
        self.assertGreater(sleep_mock.call_args.args[0], 0)


class RequestStartSmootherTest(unittest.TestCase):

    def test_disabled_by_default_does_not_sleep(self):
        s = RequestStartSmoother(rate_per_minute=0, burst=0)
        self.assertFalse(s.enabled)
        with mock.patch(
            "deepseek_cursor_gateway.rate_limiter.time.sleep"
        ) as sleep_mock:
            s.wait_if_needed()
        sleep_mock.assert_not_called()

    def test_burst_allows_immediate_requests(self):
        s = RequestStartSmoother(rate_per_minute=600.0, burst=5)
        self.assertTrue(s.enabled)
        with mock.patch(
            "deepseek_cursor_gateway.rate_limiter.time.sleep"
        ) as sleep_mock:
            for _ in range(5):
                s.wait_if_needed()
        sleep_mock.assert_not_called()

    def test_burst_exhausted_causes_sleep(self):
        with (
            mock.patch(
                "deepseek_cursor_gateway.rate_limiter.time.monotonic",
                side_effect=[0.0, 0.0, 0.0, 0.0, 0.5],
            ),
            mock.patch("deepseek_cursor_gateway.rate_limiter.time.sleep") as sleep_mock,
        ):
            s = RequestStartSmoother(rate_per_minute=120.0, burst=2)
            self.assertTrue(s.enabled)
            s.wait_if_needed()  # burst
            s.wait_if_needed()  # burst
            s.wait_if_needed()  # exhausted → sleep

        sleep_mock.assert_called_once()
        self.assertGreater(sleep_mock.call_args.args[0], 0)

    def test_smoother_does_not_hold_semaphore_slot(self):
        """Regression: smoother sleep must happen before _acquire_slot()."""
        active_during_sleep: list[int] = []

        def capture_active(_: float) -> None:
            active_during_sleep.append(tc.active)

        with (
            mock.patch(
                "deepseek_cursor_gateway.rate_limiter.time.monotonic",
                side_effect=[0.0, 0.0, 0.0, 1.0],
            ),
            mock.patch(
                "deepseek_cursor_gateway.rate_limiter.time.sleep",
                side_effect=capture_active,
            ),
        ):
            s = RequestStartSmoother(rate_per_minute=60.0, burst=1)
            tc = TrafficController(
                max_inflight=1,
                queue_timeout_seconds=5,
                retry_config=RetryConfig(enabled=False, cooldown_on_429=False),
                smoother=s,
            )
            # consume the burst token
            s.wait_if_needed()

            # The next open_upstream() call sleeps before _acquire_slot().
            with tc.open_upstream(lambda: "ok") as resp:
                self.assertEqual(resp, "ok")

        # active was 0 during the smoother sleep
        self.assertEqual(active_during_sleep, [0])

    def test_smoother_in_traffic_controller(self):
        s = RequestStartSmoother(rate_per_minute=6000.0, burst=5)
        tc = TrafficController(
            max_inflight=2,
            queue_timeout_seconds=1,
            smoother=s,
        )
        with tc.open_upstream(lambda: "ok") as resp:
            self.assertEqual(resp, "ok")
        self.assertEqual(tc.active, 0)

    def test_smoother_runs_for_each_retry_attempt(self):
        smoother = mock.Mock()
        tc = TrafficController(
            max_inflight=2,
            queue_timeout_seconds=1,
            retry_config=RetryConfig(
                enabled=True,
                max_attempts=3,
                base_delay_seconds=0.01,
                jitter_seconds=0.0,
                cooldown_on_429=False,
            ),
            smoother=smoother,
        )

        calls: list[int] = []

        def make_request() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise HTTPError("url", 503, "Service Unavailable", {}, mock.Mock())
            return "ok"

        with tc.open_upstream(make_request) as resp:
            self.assertEqual(resp, "ok")

        self.assertEqual(len(calls), 3)
        self.assertEqual(smoother.wait_if_needed.call_count, 3)


if __name__ == "__main__":
    unittest.main()
