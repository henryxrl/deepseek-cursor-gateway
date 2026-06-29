# Changelog

All notable changes to this project are documented in this file.

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
