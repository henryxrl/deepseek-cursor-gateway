# Configuration Reference

The gateway can be configured via a `config.yaml` file, CLI flags, or environment
variables (Docker). CLI flags override YAML values.

When running in Docker, use the `GATEWAY_*` environment variables listed below.
They map 1:1 to CLI flags.

---

## Upstream API

| Env var                              | YAML key                     | Default                    | Description                                           |
| ------------------------------------ | ---------------------------- | -------------------------- | ----------------------------------------------------- |
| `GATEWAY_BASE_URL`                   | `base_url`                   | `https://api.deepseek.com` | DeepSeek API base URL                                 |
| `GATEWAY_MODEL`                      | `model`                      | `deepseek-v4-pro`          | Fallback model when the request doesn't specify one   |
| `GATEWAY_THINKING`                   | `thinking`                   | `enabled`                  | `enabled` or `disabled`                               |
| `GATEWAY_REASONING_EFFORT`           | `reasoning_effort`           | `max`                      | `low`, `medium`, `high`, `max`, or `xhigh`            |
| `GATEWAY_REQUEST_TIMEOUT`            | `request_timeout`            | `300`                      | Upstream request timeout in seconds                   |
| `GATEWAY_MAX_REQUEST_BODY_BYTES`     | `max_request_body_bytes`     | `20971520`                 | Max accepted request body (20MB)                      |
| `GATEWAY_MISSING_REASONING_STRATEGY` | `missing_reasoning_strategy` | `recover`                  | `recover` (auto-recover) or `reject` (409 error)      |
| `GATEWAY_USER_MESSAGE_SUFFIX`        | `user_message_suffix`        | `""`                       | Text appended to every user message before forwarding |

---

## Traffic Control

| Env var                                     | YAML key                            | Default | Description                                        |
| ------------------------------------------- | ----------------------------------- | ------- | -------------------------------------------------- |
| `GATEWAY_UPSTREAM_MAX_INFLIGHT`             | `upstream_max_inflight`             | `2`     | Max concurrent upstream requests. `0` = unlimited. |
| `GATEWAY_UPSTREAM_QUEUE_TIMEOUT_SECONDS`    | `upstream_queue_timeout_seconds`    | `300`   | Max seconds a request waits for an upstream slot   |
| `GATEWAY_UPSTREAM_RETRY_ENABLED`            | `upstream_retry_enabled`            | `true`  | Enable retry on transient upstream errors          |
| `GATEWAY_UPSTREAM_RETRY_MAX_ATTEMPTS`       | `upstream_retry_max_attempts`       | `3`     | Total attempts including the first try             |
| `GATEWAY_UPSTREAM_RETRY_BASE_DELAY_SECONDS` | `upstream_retry_base_delay_seconds` | `2`     | Initial backoff delay                              |
| `GATEWAY_UPSTREAM_RETRY_MAX_DELAY_SECONDS`  | `upstream_retry_max_delay_seconds`  | `30`    | Cap on backoff delay                               |
| `GATEWAY_UPSTREAM_RETRY_JITTER_SECONDS`     | `upstream_retry_jitter_seconds`     | `1`     | Random jitter added to delay                       |
| `GATEWAY_UPSTREAM_RESPECT_RETRY_AFTER`      | `upstream_respect_retry_after`      | `true`  | Honor `Retry-After` header from upstream           |
| `GATEWAY_UPSTREAM_COOLDOWN_ON_429`          | `upstream_cooldown_on_429`          | `true`  | Global cooldown after any 429                      |
| `GATEWAY_REQUEST_START_RATE_LIMIT_ENABLED`  | `request_start_rate_limit_enabled`  | `false` | Optional request-start smoothing                   |
| `GATEWAY_REQUEST_START_RATE_PER_MINUTE`     | `request_start_rate_per_minute`     | `0`     | Max upstream attempt starts per minute             |
| `GATEWAY_REQUEST_START_BURST`               | `request_start_burst`               | `0`     | Burst capacity for request-start smoothing         |

---

## Image Handling

| Env var                  | YAML key         | Default | Description                 |
| ------------------------ | ---------------- | ------- | --------------------------- |
| `GATEWAY_IMAGE_HANDLING` | `image_handling` | `strip` | `strip`, `reject`, or `ocr` |

### OCR / Vision Backend (only when `image_handling=ocr`)

| Env var                   | YAML key          | Default             | Description                                   |
| ------------------------- | ----------------- | ------------------- | --------------------------------------------- |
| `GATEWAY_VISION_BACKEND`  | `vision_backend`  | `openai_compatible` | `openai_compatible`, `gemini`, or `tesseract` |
| `GATEWAY_VISION_BASE_URL` | `vision_base_url` | —                   | Base URL for the vision API (OpenAI-compatible or Gemini) |
| `GATEWAY_VISION_MODEL`    | `vision_model`    | `gpt-4o-mini`       | Vision model name                             |
| `GATEWAY_VISION_API_KEY`  | `vision_api_key`  | `""`                | API key for the vision backend                |
| `GATEWAY_VISION_TIMEOUT`  | `vision_timeout`  | `60`                | Vision API timeout in seconds                 |
| `GATEWAY_VISION_CONCURRENCY` | `vision_concurrency` | `0`              | Max concurrent vision API calls; `0` = unlimited. Use 1 or 2 for local LLMs |
| `GATEWAY_VISION_WARMUP`   | `vision_warmup`   | `warn`              | Startup warm-up for remote vision backends: `off`, `warn`, or `require` |
| `GATEWAY_VISION_FALLBACK_BACKEND` | `vision_fallback_backend` | `""` | Optional fallback backend; currently `tesseract` |
| `GATEWAY_TESSERACT_LANG`  | `tesseract_lang`  | `eng+chi_sim`       | Tesseract language code(s)                    |

### OCR Security & Cache (YAML-only)

These advanced settings are configured in `config.yaml` only — there are no
corresponding `GATEWAY_*` environment variables.

| YAML key                          | Default             | Description                                      |
| --------------------------------- | ------------------- | ------------------------------------------------ |
| `image_max_bytes`                 | `20971520`          | Max bytes per image (20 MB)                      |
| `image_max_count`                 | `10`                | Max images per request                           |
| `image_max_base64_bytes`          | `52428800`          | Max total base64 bytes across all images (50 MB) |
| `image_allow_local_urls`          | `false`             | Allow `http://` and loopback for local dev       |
| `image_ocr_cache_path`            | `image_ocr.sqlite3` | OCR cache SQLite path                            |
| `image_ocr_cache_max_age_seconds` | `2592000`           | Max cache row age (30 days)                      |
| `image_ocr_cache_max_rows`        | `10000`             | Max cache rows                                   |

---

## Reasoning Cache

| Env var                                   | YAML key                          | Default                           | Description                 |
| ----------------------------------------- | --------------------------------- | --------------------------------- | --------------------------- |
| `GATEWAY_REASONING_CONTENT_PATH`          | `reasoning_content_path`          | `/data/reasoning_content.sqlite3` | SQLite cache path           |
| `GATEWAY_REASONING_CACHE_MAX_AGE_SECONDS` | `reasoning_cache_max_age_seconds` | `2592000`                         | Max cache row age (30 days) |
| `GATEWAY_REASONING_CACHE_MAX_ROWS`        | `reasoning_cache_max_rows`        | `100000`                          | Max cache rows              |

---

## Display

| Env var                         | YAML key                | Default | Description                                   |
| ------------------------------- | ----------------------- | ------- | --------------------------------------------- |
| `GATEWAY_DISPLAY_REASONING`     | `display_reasoning`     | `true`  | Mirror reasoning_content into visible content |
| `GATEWAY_COLLAPSIBLE_REASONING` | `collapsible_reasoning` | `true`  | Wrap mirrored reasoning in `<details>` HTML   |

---

## Network & Misc

| Env var             | YAML key    | Default             | Description                                           |
| ------------------- | ----------- | ------------------- | ----------------------------------------------------- |
| `GATEWAY_HOST`      | `host`      | `127.0.0.1`         | Bind address                                          |
| `GATEWAY_PORT`      | `port`      | `9000`              | Bind port                                             |
| `GATEWAY_NGROK`     | `ngrok`     | `true`              | Start an ngrok tunnel (disabled by default in Docker) |
| `GATEWAY_NGROK_URL` | `ngrok_url` | —                   | Custom ngrok URL / reserved domain                    |
| `GATEWAY_VERBOSE`   | `verbose`   | `false`             | Log full request/response payloads                    |
| `GATEWAY_CORS`      | `cors`      | `false`             | Send permissive CORS headers                          |
| `GATEWAY_TRACE_DIR` | `trace_dir` | —                   | Write structured request traces to disk               |
| `GATEWAY_CONFIG`    | —           | `/data/config.yaml` | YAML config file path                                 |

---

## Boolean Values

Boolean env vars accept (case-insensitive):

| Truthy                   | Falsy                     |
| ------------------------ | ------------------------- |
| `1`, `true`, `yes`, `on` | `0`, `false`, `no`, `off` |

Unset variables are not passed as arguments — the program uses its own defaults.

---

## Example `.env`

```bash
# Upstream
GATEWAY_BASE_URL=https://api.deepseek.com
GATEWAY_MODEL=deepseek-v4-pro
GATEWAY_THINKING=enabled
GATEWAY_REASONING_EFFORT=max

# Traffic control
GATEWAY_UPSTREAM_MAX_INFLIGHT=2
GATEWAY_UPSTREAM_QUEUE_TIMEOUT_SECONDS=300
GATEWAY_UPSTREAM_RETRY_MAX_ATTEMPTS=3
GATEWAY_UPSTREAM_COOLDOWN_ON_429=1

# Optional burst smoothing; disabled by default
GATEWAY_REQUEST_START_RATE_LIMIT_ENABLED=0

# Image handling — use Tesseract for local OCR
GATEWAY_IMAGE_HANDLING=ocr
GATEWAY_VISION_BACKEND=tesseract
GATEWAY_TESSERACT_LANG=eng+chi_sim
```
