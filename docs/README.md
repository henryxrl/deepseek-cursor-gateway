# DeepSeek Cursor Gateway

A Docker-first gateway that makes [Cursor](https://cursor.com) work seamlessly
with [DeepSeek V4](https://api-docs.deepseek.com) models, including
reasoning-content preservation, upstream traffic control, and image input
support.

This is the maintained Docker-first gateway fork of the original
`deepseek-cursor-proxy`, with the following additions.

---

## Features

### Reasoning-Content Preservation (upstream)

Cursor strips DeepSeek's `reasoning_content` from assistant messages. The
gateway caches it in SQLite and restores it across turns, so tool-call reasoning
is never lost. If the cache misses, it automatically recovers by truncating
the conversation to the latest user message.

### Upstream Traffic Control

Cursor's agent mode can fire multiple chat-completion requests in quick
succession. The gateway adds guards so you don't hit DeepSeek rate limits:

- **Concurrency gate** — limit how many upstream requests are active at once
  (default 2).
- **Queue timeout** — if all slots are occupied, new requests wait up to a
  configurable timeout before returning a local error.
- **Automatic retry** — retries on 429 / 502 / 503 / 504 with exponential
  backoff and jitter.
- **Retry-After** — honors the `Retry-After` header when present.
- **Global cooldown** — after a 429, all threads wait before trying again,
  preventing a stampede.

[Read more →](rate-limiting.md)

### Image Input Handling

DeepSeek text models do not accept image blocks. The gateway converts images
to text before forwarding:

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

[Read more →](image-handling.md)

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

Your DeepSeek API key stays in Cursor — the gateway forwards it from Cursor's
`Authorization` header. You never put it in a config file.

[Full deployment guide →](deployment.md)

---

## Configuration

All behaviour is configured via environment variables (Docker) or a
`config.yaml` file (local). See the full reference:

[Configuration reference →](configuration.md)
