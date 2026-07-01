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

- [Configuration reference →](configuration.md)

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
# Health check
curl http://localhost:9000/healthz
# → {"ok": true}

# List models
curl http://localhost:9000/v1/models
# → shows DeepSeek models
```

To check that the traffic controller is active, enable verbose logging in `.env`, recreate the container, and watch the logs:

```bash
# Add this to .env:
# GATEWAY_VERBOSE=1

docker compose up -d --force-recreate
docker compose logs -f deepseek-cursor-gateway
```

Watch for lines like:

```
traffic slot_wait_ms=... active=... max=...
retry attempt=... delay_ms=...
```

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
