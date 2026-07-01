# Deployment

---

## Quick Start (Pre-built Image)

```bash
# 1. Create .env from template
cp .env.example .env

# 2. Edit .env with your configuration
vim .env

# 3. Pull and start
docker compose up -d
```

`docker-compose.yml` pulls `ghcr.io/henryxrl/deepseek-cursor-gateway:latest` — no local build needed.

After startup, set Cursor's **API Base URL** to `http://localhost:9000/v1`.

---

## Local Development Build

If you're building from source or testing local changes:

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

`docker-compose.dev.yml` builds the image from the current directory with `build: .` (includes Tesseract in the image).

---

## Environment Variables

See the full reference:

- [Configuration Reference](configuration.md)

A minimal `.env`:

```bash
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=9000
GATEWAY_BASE_URL=https://api.deepseek.com
GATEWAY_MODEL=deepseek-v4-pro

# Optional: enable OCR with local Tesseract
GATEWAY_IMAGE_HANDLING=ocr
GATEWAY_VISION_BACKEND=tesseract
```

---

## Plain Docker (without Compose)

```bash
docker run -d \
  --name deepseek-cursor-gateway \
  -p 9000:9000 \
  -v gateway-data:/data \
  --restart unless-stopped \
  ghcr.io/henryxrl/deepseek-cursor-gateway:latest
```

Override defaults with `-e`:

```bash
docker run -d \
  --name deepseek-cursor-gateway \
  -p 9000:9000 \
  -v gateway-data:/data \
  --restart unless-stopped \
  -e GATEWAY_MODEL=deepseek-v4-pro \
  -e GATEWAY_THINKING=enabled \
  -e GATEWAY_REASONING_EFFORT=max \
  -e GATEWAY_UPSTREAM_MAX_INFLIGHT=2 \
  ghcr.io/henryxrl/deepseek-cursor-gateway:latest
```

---

## Verifying the Gateway

```bash
# Health check (version + uptime)
curl http://localhost:9000/healthz
# → {"ok": true, "version": "<version>", "uptime_seconds": 123.45}

# Health check with upstream reachability probe (GET to upstream /models, 5s timeout)
curl "http://localhost:9000/healthz?upstream=1"
# → {"ok": true, "version": "<version>", "uptime_seconds": 123.45,
#     "upstream_reachable": true, "probe_url": "...", "probe_status": 401, "probe_error_type": "http_error"}
# Note: upstream_reachable means HTTP connectivity, not valid API credentials.

# Readiness (cache DB, traffic controller, OCR / vision warm-up when applicable)
curl http://localhost:9000/readyz
# → {"ready": true, "version": "<version>", "checks": {...}}

# Runtime configuration (grouped JSON, no secrets)
curl http://localhost:9000/info
# → {"version": "<version>", "upstream": {...}, "image_handling": {...}, ...}

# Prometheus metrics (text format)
curl http://localhost:9000/metrics

# List models (includes -nothink variants for thinking toggle)
curl http://localhost:9000/v1/models
# → deepseek-v4-pro, deepseek-v4-pro-nothink, deepseek-v4-flash, ...
```

`/info` groups settings into `upstream`, `image_handling`, `display`, `reasoning_cache`, `traffic_control`, and `network`. API keys, file paths, and other sensitive values are never included.

For Docker health checks, a lightweight probe is enough:

```bash
curl -f http://localhost:9000/healthz
```

To also verify DeepSeek reachability (slower, needs outbound network):

```bash
curl -f "http://localhost:9000/healthz?upstream=1" | jq -e '.upstream_reachable == true'
```

### Docker Compose healthcheck

The image includes Python but not `curl`. Add a `healthcheck` to your Compose service (or override file) to let Docker mark the container unhealthy when the process stops responding:

```yaml
services:
  deepseek-cursor-gateway:
    healthcheck:
      test:
        - CMD-SHELL
        - python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/healthz', timeout=3)"
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
```

Use `/healthz` only — do not point Docker healthchecks at `?upstream=1`; the external probe is slower and can fail when DeepSeek is briefly unreachable even though the gateway is fine. Use `/readyz` in deployment systems that need dependency checks (cache writable, OCR warm-up known). Adjust `9000` if `GATEWAY_PORT` is not the default.

### Docker image smoke tests

Before a release, run the container smoke script (requires Docker):

```bash
bash tests/test_docker_smoke.sh
```

This builds the image and verifies `deepseek-cursor-gateway --help`, Tesseract language packs, and **host-side** access through the published port to `/healthz`, `/readyz`, `/v1/models`, and `/metrics`.

### Prometheus scraping

The gateway serves metrics at `/metrics` with no extra configuration. A minimal Prometheus `scrape_configs` entry:

```yaml
scrape_configs:
  - job_name: deepseek-cursor-gateway
    scrape_interval: 30s
    metrics_path: /metrics
    static_configs:
      - targets: ['localhost:9000']   # host machine
```

When Prometheus runs in the same Compose network, scrape by service name instead:

```yaml
    static_configs:
      - targets: ['deepseek-cursor-gateway:9000']
```

Bind the gateway to localhost or protect `/metrics` at your reverse proxy if the port is exposed beyond your homelab.

### Observing traffic control

Use `/metrics` and `request_manifest` logs — no verbose mode required:

```bash
# Queue wait, active upstream slots, retries, cooldowns
curl -s http://localhost:9000/metrics | grep -E 'queue|upstream_active|retry|cooldown'

# Per-request summary (status, model, stream, elapsed_ms, upstream_status)
docker compose logs -f deepseek-cursor-gateway | grep request_manifest
```

For full request/response bodies during debugging, set `GATEWAY_VERBOSE=1` in `.env` and recreate the container. Retry events also log as `retry attempt=... delay_ms=...`.

See [Upstream Traffic Control](rate-limiting.md#logs-and-metrics-to-watch) for tuning guidance.

---

## Data Persistence

The named volume `gateway-data` mounted at `/data` persists:

| File                              | Purpose                                            |
| --------------------------------- | -------------------------------------------------- |
| `/data/reasoning_content.sqlite3` | Reasoning-content cache                            |
| `/data/config.yaml`               | Auto-generated config file                         |
| `/data/image_ocr.sqlite3`         | OCR result cache (when using `image_handling=ocr`) |
| `/data/traces/`                   | Request traces (when `GATEWAY_TRACE_DIR` is set)   |

---

## Upgrading

```bash
# Pre-built image
docker compose pull
docker compose up -d

# Local build
docker compose -f docker-compose.dev.yml up -d --build
```

The data volume is preserved across upgrades. Cache files are compatible.
