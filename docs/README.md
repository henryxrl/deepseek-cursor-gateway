# DeepSeek Cursor Gateway

A Docker-first gateway that makes [Cursor](https://cursor.com) work seamlessly with [DeepSeek V4](https://api-docs.deepseek.com) models, including reasoning-content preservation, upstream traffic control, and image input support.

This is the maintained Docker-first gateway fork of the original `deepseek-cursor-proxy`, with the following additions.

### HTTP API Endpoints

The gateway exposes a few useful GET endpoints in addition to the main proxy at `/v1/chat/completions`:

| Endpoint | Description |
| -------- | ----------- |
| `/healthz`, `/v1/healthz` | Liveness — `ok`, `version`, `uptime_seconds`; add `?upstream=1` for upstream **reachability** probe (not auth) |
| `/readyz`, `/v1/readyz` | Readiness — `ready` plus checks for reasoning cache, traffic controller, OCR cache, vision warm-up |
| `/info`, `/v1/info` | Runtime configuration (grouped JSON, safe subset — no secrets) |
| `/metrics` | Prometheus-format metrics — requests, latency summaries, queue/active upstream, cache, recovery |
| `/models`, `/v1/models` | Available DeepSeek models (includes `-nothink` variants for per-request thinking toggle) |

---

## Features

### Reasoning-Content Preservation (upstream)

Cursor strips DeepSeek's `reasoning_content` from assistant messages. The gateway caches it in SQLite and restores it across turns, so tool-call reasoning is never lost. If the cache misses, it automatically recovers by truncating the conversation to the latest user message.

### Thinking Control

Override the global `thinking` setting per request without restarting the gateway:

- **Request body** — standard DeepSeek `thinking` field (highest priority)
- **Model suffix** — append `-nothink` to the model name (stripped before forwarding)
- **Model list** — `/v1/models` exposes `-nothink` variants for clients that populate the picker from the API

See [Configuration Reference — Per-Request Thinking Override](configuration.md#per-request-thinking-override) for priority rules and examples.

### Upstream Traffic Control

Cursor's agent mode can fire multiple chat-completion requests in quick succession. The gateway adds guards so you don't hit DeepSeek rate limits:

- **Concurrency gate** — limit how many upstream requests are active at once (default 2).
- **Queue timeout** — if all slots are occupied, new requests wait up to a configurable timeout before returning a local error.
- **Automatic retry** — retries on 429 / 502 / 503 / 504 with exponential backoff and jitter.
- **Retry-After** — honors the `Retry-After` header when present.
- **Global cooldown** — after a 429, all threads wait before trying again, preventing a stampede.

[Read more in Upstream Traffic Control](rate-limiting.md)

### Image Input Handling

DeepSeek text models do not accept image blocks. The gateway converts images to text before forwarding:

| Mode              | Behaviour                                                                                                                                   |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `strip` (default) | Removes image blocks, replaces with a placeholder. Matches the original proxy's behaviour.                                                  |
| `reject`          | Returns a clear HTTP 400 error when images are detected. Useful for debugging.                                                              |
| `ocr`             | Extracts text from images using a vision model and replaces image blocks with text descriptions. DeepSeek can then "see" the image content. |

OCR supports three backends:

| Backend             | Description                                                                      |
| ------------------- | -------------------------------------------------------------------------------- |
| `openai_compatible` | Any OpenAI-compatible vision endpoint (GPT-4o-mini, vLLM, Ollama, LiteLLM, etc.) |
| `gemini`            | Google Gemini API (native format)                                                |
| `tesseract`         | Local OCR engine — fast, free, no API key needed                                 |

[Read more in Image Input Handling](image-handling.md)

### Prometheus Metrics

The gateway exposes operational metrics at `/metrics` in Prometheus text format — no third-party client library needed. Included metrics:

| Metric | Type | Description |
| ------ | ---- | ----------- |
| `gateway_requests_total` | counter | Requests by path and HTTP status |
| `gateway_upstream_errors_total` | counter | Upstream errors by HTTP status |
| `gateway_retry_attempts_total` | counter | Total upstream retry attempts |
| `gateway_cooldown_total` | counter | Global 429 cooldown events |
| `gateway_reasoning_cache_hits_total` | counter | Reasoning cache hits |
| `gateway_reasoning_cache_misses_total` | counter | Reasoning cache misses |
| `gateway_reasoning_cache_hit_ratio` | gauge | Hit ratio (hits / total lookups) |
| `gateway_upstream_active_requests` | gauge | Active upstream requests |
| `gateway_upstream_request_duration_seconds` | summary | Upstream request duration |
| `gateway_queue_wait_duration_seconds` | summary | Time waiting for an upstream slot |
| `gateway_ocr_cache_hits_total` | counter | OCR cache hits |
| `gateway_ocr_cache_misses_total` | counter | OCR cache misses |
| `gateway_ocr_duration_seconds` | summary | OCR vision call duration |
| `gateway_recovery_total` | counter | Reasoning recovery events |
| `gateway_missing_reasoning_total` | counter | Missing reasoning occurrences |

Each completed chat request also emits a structured `request_manifest` log line (`status`, `model`, `stream`, `image_count`, `recovery`, `upstream_status`, `elapsed_ms`). When trace logging is enabled, the same summary is stored under `completion.manifest` in the trace JSON.

Scrape with Prometheus or `curl http://localhost:9000/metrics`. See [Deployment](deployment.md) for verification examples.

---

## Quick Start

```bash
# 1. Create your config
cp .env.example .env
# Edit .env with your DeepSeek API configuration

# 2. Start the gateway
docker compose up -d

# 3. Set Cursor's API Base URL to
#    http://localhost:9000/v1
```

Your DeepSeek API key stays in Cursor — the gateway forwards it from Cursor's `Authorization` header. You never put it in a config file.

[Deployment](deployment.md)

---

## Configuration

All behaviour is configured via environment variables (Docker) or a `config.yaml` file (local). See the full reference:

[Configuration Reference](configuration.md)
