# Changelog

All notable changes to this project are documented in this file.

---

## [0.2.6] — 2026-06-30

### Added

- **`/readyz` endpoint** — readiness probe with per-component checks (`reasoning_cache`, `traffic_controller`, `ocr_cache`, `vision_warmup`). Returns HTTP 503 when not ready.
- **Extended metrics** — upstream request duration, queue wait duration, active upstream requests gauge, OCR cache hit/miss, recovery and missing-reasoning counters.
- **Upstream reachability diagnostics** — `/healthz?upstream=1` now includes `probe_url`, `probe_status`, and `probe_error_type` (reachability only; not auth).
- **Request manifest** — each completed request logs a `request_manifest` line and writes a `manifest` summary into trace completion (`status`, `model`, `stream`, `image_count`, `recovery`, `upstream_status`, `elapsed_ms`).
- **Docker smoke script** — `tests/test_docker_smoke.sh` validates image help, Tesseract languages, and `/healthz`, `/readyz`, `/models`, `/metrics`.
- **Observability tests** — `tests/test_observability.py` covers probes, metrics, `/info` redaction, readiness, and manifests.

### Changed

- `probe_upstream()` uses GET (not HEAD) and treats 4xx as reachable; documented as reachability, not credential validation.
- `maybe_warm_up_vision()` returns `(config, warmup_state)` for readiness reporting.
- Documentation — root README `--no-ngrok` for native runs; observability summary; rate-limiting/deployment troubleshooting aligned with `/metrics` and `request_manifest`; DocMD site URL and CI deploy path; exclude `docs/dev/` from doc site build.

### Fixed

- Queue timeout handler restores 503 JSON response and trace completion.
- Metrics singleton unified via `wire_gateway_metrics()` so `/metrics` reflects retry, cache, and cooldown activity.

---

## [0.2.5] — 2026-06-30

### Added

- **Prometheus metrics** — `/metrics` endpoint in Prometheus text format: request counts, upstream errors, retry/cooldown counters, reasoning cache hit ratio.

### Changed

- Documentation — deployment healthcheck/Prometheus scrape examples; observability cross-links

### Fixed

- `ReasoningStore.close()` no longer raises on repeated calls.
- `GatewayMetrics.global_instance()` race condition under concurrent initialization.
- `do_POST` error paths (400, 413, 502, 503, upstream HTTP errors) now recorded in request metrics.

---

## [0.2.4] — 2026-06-30

### Added

- **Health & info endpoints** — `/healthz` returns `ok`, `version`, and `uptime_seconds`; add `?upstream=1` to probe DeepSeek reachability (`upstream_reachable`). New `/info` endpoint exposes grouped runtime configuration (no secrets).
- **Model list `-nothink` variants** — `/v1/models` now lists each base model with a `-nothink` suffix variant for per-request thinking toggle (OpenAI-compatible; other clients can ignore extra entries).

### Changed

- `/info` response grouped into `upstream`, `image_handling`, `display`, `reasoning_cache`, `traffic_control`, and `network` sections.

---

## [0.2.3] — 2026-06-30

### Added

- **Per-request thinking override** — model name `-nothink` suffix and request-body `thinking` field allow overriding the global thinking setting without config changes.

### Changed

- `server_version` now reads dynamically from package `__version__` (`0.2.3`) instead of hardcoded `DeepSeekPythonGateway/0.1`.
- Removed backward-compatible misspelled `collasible_reasoning` config key; only `collapsible_reasoning` is accepted.

### Fixed

- Dead `store_finished_reasoning` method removed from `StreamAccumulator`; tests migrated to `store_ready_reasoning`.
- Documentation paragraphs unwrapped — mid-sentence hard line breaks removed across all docs for readability.
- CHANGELOG backfilled with 0.2.1 and 0.2.2 release notes.

---

## [0.2.2] — 2026-06-30

### Added

- **Vision warm-up & fallback** — `GATEWAY_VISION_WARMUP` (off | warn | require) probes remote vision backends on startup; `GATEWAY_VISION_FALLBACK_BACKEND` (tesseract) provides automatic fallback when the primary vision backend fails, both during warm-up and at runtime.
- **Portable turn-scoped reasoning cache** — cross-mode (Agent↔Plan) and cross-model (Pro↔Flash) reasoning content sharing via portable alias keys, enabling continuation after mode switches without losing reasoning history.

### Fixed

- Valid vision warm-up PNG bytes.
- Missing verbose logging for streaming reasoning cache store.

---

## [0.2.1] — 2026-06-29

### Added

- `GATEWAY_VISION_CONCURRENCY` — limits parallel vision API calls via a bounded semaphore (default unlimited). Use 1 or 2 for local LLMs with limited resources.

---

## [0.2.0] — 2026-06-28

### Added

- **Rate limiting** — concurrency gate (default 2) and configurable queue timeout to prevent overwhelming upstream DeepSeek APIs when Cursor agent mode fires multiple requests in quick succession.
- **Image input support** — automatic image extraction from OpenAI-compatible messages, with local OCR (Tesseract) integration for text-heavy images, content-based deduplication via SHA-256 caching, and IP-based URL allowlisting.
- **Comprehensive documentation** — new `docs/` directory covering configuration, deployment (Docker & native), image handling, and rate limiting.
- **New test suite coverage** — unit tests for rate limiter, image handler, entrypoint script, and expanded server/trace tests.

### Changed

- **Project renamed** to **DeepSeek Cursor Gateway** (`deepseek-cursor-gateway`), reflecting its expanded scope beyond a simple proxy.
- **Server overhaul** — integrated rate limiting and image handling into the request pipeline; added health endpoint (`/health`); improved error responses for rate-limited and misconfigured requests.
- **Configuration expanded** — `config.py` now supports rate-limit settings (concurrency, timeout, endpoint-specific rules), image handling (Tesseract path, URL allowlist, cache DB path), and enhanced environment-variable mapping in `.env.example`.
- **Docker improvements** — updated `Dockerfile` for smaller layers, refined `docker-compose.yml` and `docker-compose.dev.yml` for easier local development, and improved entrypoint script with better error handling.
- **Tracing enhancements** — `trace.py` extended with additional diagnostic fields for rate-limiting and image-processing events.
- **Dependencies** — `pyproject.toml` updated; version now reads from `VERSION` file as single source of truth.

### Removed

- **`DOCKER.md`** — replaced by `docs/deployment.md` with expanded deployment instructions.

---

## [0.1.1] — 2026-06-27

Upstream baseline from [deepseek-cursor-proxy-turbo](https://github.com/abcduyt1243-git/deepseek-cursor-proxy-turbo), which includes:

- Reasoning-content preservation via SQLite cache with automatic recovery
- Ngrok tunnel support for fixed endpoint URLs
- Collapsible reasoning display in streaming responses
- Request tracing and diagnostics (`trace.py`)
- Optimized reasoning store with SQLite caching
- Docker support with Dockerfile, docker-compose, and CI/CD workflows
- Comprehensive bilingual README with setup guide

> This version tracks the upstream `main` branch as of June 27, 2026 and serves as the baseline for the gateway fork.
