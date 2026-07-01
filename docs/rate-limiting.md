# Upstream Traffic Control

DeepSeek enforces account-level concurrency limits (500 for V4 Pro, 2500 for V4 Flash). While a single Cursor session won't approach those numbers, agent mode can fire multiple requests in quick succession — and long-context thinking requests take time. The gateway adds three layers of protection.

---

## Concurrency Gate

`upstream_max_inflight` limits how many upstream DeepSeek requests are active at the same time. The limit covers the **entire upstream lifecycle**: from the moment `urlopen()` is called until the full response body is consumed (including streaming). Default is `2`.

```bash
GATEWAY_UPSTREAM_MAX_INFLIGHT=2
```

Set to `0` to disable the gate entirely (unlimited concurrency).

```text
GATEWAY_UPSTREAM_MAX_INFLIGHT=0
```

### Queue Timeout

If all slots are occupied, new requests wait instead of failing immediately. `upstream_queue_timeout_seconds` caps the wait time. When the timeout expires, the gateway returns HTTP 503 to Cursor without calling DeepSeek.

```bash
GATEWAY_UPSTREAM_QUEUE_TIMEOUT_SECONDS=300
```

The error response:

```json
{
    "error": {
        "message": "Timed out waiting for an upstream DeepSeek slot after 300s…",
        "type": "gateway_upstream_queue_timeout",
        "code": "gateway_upstream_queue_timeout"
    }
}
```

---

## Automatic Retry

The gateway retries on transient upstream errors:

- **Retryable**: `429` (rate limit), `502`, `503`, `504`
- **Not retryable**: `400`, `401`, `403`, reasoning-content contract errors

```bash
GATEWAY_UPSTREAM_RETRY_ENABLED=1         # on/off
GATEWAY_UPSTREAM_RETRY_MAX_ATTEMPTS=3    # total tries including the first
GATEWAY_UPSTREAM_RETRY_BASE_DELAY_SECONDS=2
GATEWAY_UPSTREAM_RETRY_MAX_DELAY_SECONDS=30
GATEWAY_UPSTREAM_RETRY_JITTER_SECONDS=1  # random jitter
```

### Backoff Algorithm

```text
delay = base_delay × 2^attempt + random(0, jitter)
delay = min(delay, max_delay)
```

### Retry-After Header

When `GATEWAY_UPSTREAM_RESPECT_RETRY_AFTER=1` (the default), the gateway reads the `Retry-After` header from 429 responses. If present, it waits that duration instead of computing its own backoff.

The header is parsed as either:

- **Delta seconds**: `Retry-After: 120`
- **HTTP date**: `Retry-After: Wed, 21 Oct 2025 07:28:00 GMT`

---

## Global Cooldown

When one request gets a 429, **all** threads pause before calling DeepSeek again. This prevents a stampede: without it, every queued Cursor request would immediately retry, likely hitting 429 again.

```bash
GATEWAY_UPSTREAM_COOLDOWN_ON_429=1
```

The cooldown duration equals the backoff delay computed for the 429 response.
While the cooldown is active, new upstream attempts wait before acquiring a slot. Retry events appear in logs as:

```text
retry attempt=1/3 delay_ms=...
```

### Important: Retries happen before Cursor receives headers

All retry logic runs before the gateway sends response headers to Cursor. Once a streaming response has started, retry is not possible — Cursor has already begun processing.

---

## Optional Request-Start Smoothing

The concurrency gate is the primary limiter. If you still observe very bursty request starts, you can enable an optional token-bucket smoother. It delays before an upstream request attempt starts, and it does **not** hold an upstream slot while waiting.

It is disabled by default:

```bash
GATEWAY_REQUEST_START_RATE_LIMIT_ENABLED=0
```

Example:

```bash
GATEWAY_REQUEST_START_RATE_LIMIT_ENABLED=1
GATEWAY_REQUEST_START_RATE_PER_MINUTE=30
GATEWAY_REQUEST_START_BURST=3
```

Use this only after observing burst-related issues. For most Cursor use, the default concurrency gate plus 429 cooldown is enough.

---

## Logs and Metrics to Watch

### Prometheus (`/metrics`)

The primary way to observe traffic control without verbose logging:

```bash
curl -s http://localhost:9000/metrics | grep -E 'queue|upstream_active|retry|cooldown'
```

| Metric | What it tells you |
| ------ | ----------------- |
| `gateway_queue_wait_duration_seconds` | Time requests spent waiting for an upstream slot |
| `gateway_upstream_active_requests` | How many upstream calls are in flight right now |
| `gateway_upstream_request_duration_seconds` | End-to-end upstream request duration |
| `gateway_retry_attempts_total` | Retry count |
| `gateway_cooldown_total` | Global 429 cooldown events |

Queue wait **sum/count rising** means gateway-side queueing; **retry/cooldown** counters rising means DeepSeek rate limiting.

### Request manifest logs

Every completed chat request emits one structured line (no `GATEWAY_VERBOSE` needed):

```text
request_manifest status=completed model=deepseek-v4-pro stream=false image_count=0 recovery=false missing_reasoning=0 upstream_status=200 elapsed_ms=...
```

Use `status=queue_timeout` or `upstream_error` to spot local queue saturation vs upstream failures.

### Verbose mode (optional)

For full request/response bodies, enable:

```bash
GATEWAY_VERBOSE=1
```

Retry attempts also log as:

```text
retry attempt=1/3 delay_ms=...
```

See [DeepSeek Cursor Gateway](README.md) for the full metric list.

---

## Tuning Guide

| Scenario                                      | Adjustment                                               |
| --------------------------------------------- | -------------------------------------------------------- |
| Cursor feels sluggish, queue wait metrics rising | Increase `upstream_max_inflight` to 3 or 4               |
| Getting 429s from DeepSeek                    | Keep `cooldown_on_429=1`; reduce `upstream_max_inflight` |
| Retries too slow                              | Lower `base_delay_seconds` or `max_delay_seconds`        |
| Testing / debugging                           | Set `upstream_max_inflight=0`, `retry_enabled=0`         |
