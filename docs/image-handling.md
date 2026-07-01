# Image Input Handling

DeepSeek V4 text models do not accept `image_url` content blocks. Cursor may send images (screenshots, pasted images, base64 data URLs). The gateway can handle these in three modes.

---

## Modes

| Mode     | Behaviour                                                                            | When to use                                    |
| -------- | ------------------------------------------------------------------------------------ | ---------------------------------------------- |
| `strip`  | Removes image blocks, inserts a placeholder. DeepSeek sees text only.                | Default — safe and reliable.                   |
| `reject` | Returns HTTP 400 before calling DeepSeek.                                            | Debugging: confirm which requests have images. |
| `ocr`    | Extracts text from images using a vision model. DeepSeek receives text descriptions. | Best UX — DeepSeek can "see" image content.    |

Set the mode:

```bash
GATEWAY_IMAGE_HANDLING=strip   # default
GATEWAY_IMAGE_HANDLING=reject
GATEWAY_IMAGE_HANDLING=ocr
```

---

## Mode: `strip` (default)

Images are replaced with a placeholder:

```text
[Image omitted: DeepSeek text models do not support image input.]
```

The gateway logs how many images were detected:

```text
image detected image_handling=strip image_count=3 request_path=/v1/chat/completions
```

---

## Mode: `reject`

If any image block is detected, the gateway returns HTTP 400 immediately — no upstream call is made.

```json
{
    "error": {
        "message": "Image input was detected (3 image block(s)), but image handling is set to 'reject'…",
        "type": "unsupported_media",
        "code": "image_input_not_supported"
    }
}
```

---

## Mode: `ocr`

Each image is converted to text before forwarding to DeepSeek.

### Pipeline

```text
╔══════════════════╗
║ Cursor sends     ║
║ image_url blocks ║
╚══════╤═══════════╝
       │
       ▼
┌──────────────────┐
│ Extract images   │  ← detects every image_url part across all messages
└──────┬───────────┘
       │
       ▼
┌──────────────────┐     ┌─────────────────┐
│ For each image:  │     │ OCR Cache       │
│  sha256(bytes) ──┼───→ │ (SQLite)        │
└──────┬───────────┘     │ hit → skip API  │
       │                 │ miss → call      │
       ▼                 └─────────────────┘
┌──────────────────┐
│ Vision backend   │  ← openai_compatible / gemini / tesseract
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Replace image    │  text block: "[Image attachment…]\nOCR summary:\n…"
│ block with text  │
└──────┬───────────┘
       │
       ▼
╔══════════════════╗
║ DeepSeek         ║
║ receives text    ║
╚══════════════════╝
```

### Multiple Images

You can paste multiple images in a single message. Each image is processed independently, with its own cache key. Repeated images hit the cache and skip the vision API.

Security limits:

- Max 10 images per request (`image_max_count`)
- Max 20 MB per image (`image_max_bytes`)
- Max 50 MB total base64 data (`image_max_base64_bytes`)

### Security

When fetching remote image URLs, the gateway enforces:

- **Scheme whitelist**: `https://` only (configurable `http://` for local)
- **SSRF protection**: blocks private/reserved IPs (`10/8`, `192.168/16`, etc.)
- **MIME validation**: only `image/png`, `image/jpeg`, `image/gif`, `image/webp`

Traces and verbose logs never include image data or OCR results.

---

## Vision Backends

Choose a backend with `GATEWAY_VISION_BACKEND`.

### OpenAI-Compatible

Any service that speaks the OpenAI `/v1/chat/completions` format.

```bash
GATEWAY_VISION_BACKEND=openai_compatible
GATEWAY_VISION_BASE_URL=https://api.openai.com/v1
GATEWAY_VISION_MODEL=gpt-4o-mini
GATEWAY_VISION_API_KEY=sk-...
GATEWAY_VISION_TIMEOUT=60
GATEWAY_VISION_CONCURRENCY=0             # 0 = unlimited; set to 1 or 2 for local LLMs
GATEWAY_VISION_WARMUP=warn               # off | warn | require
GATEWAY_VISION_FALLBACK_BACKEND=tesseract # optional fallback when LLM vision fails
```

Works with:

- **OpenAI**: `gpt-4o-mini`, `gpt-4o`
- **vLLM / Ollama**: any local vision model with an OpenAI-compatible endpoint
- **LiteLLM**: `http://litellm:4000/v1`

`GATEWAY_VISION_CONCURRENCY` limits how many vision API calls can run in parallel. Most cloud APIs handle many concurrent requests, but local LLMs (vLLM/Ollama) typically only support 1–2 simultaneous calls. Set this to match your local model's capacity; `0` (the default) means unlimited.

When OCR mode uses a remote vision backend, the gateway sends a tiny warm-up image on startup by default (`GATEWAY_VISION_WARMUP=warn`). A failed warm-up is logged and startup continues; set it to `require` to fail startup instead, or `off` to skip the probe. Set `GATEWAY_VISION_FALLBACK_BACKEND=tesseract` to use local Tesseract when the primary LLM vision backend fails.

The gateway sends a prompt asking the model to "describe this image in detail, including any visible text, UI elements, code, diagrams, or screenshots."

### Gemini

Uses Google's native `generateContent` API. Defaults to `https://generativelanguage.googleapis.com/v1beta`; set `GATEWAY_VISION_BASE_URL` to point to a proxy or Vertex AI endpoint.

```bash
GATEWAY_VISION_BACKEND=gemini
GATEWAY_VISION_MODEL=gemini-2.0-flash
GATEWAY_VISION_API_KEY=...
GATEWAY_VISION_TIMEOUT=60
# Optional: custom endpoint (e.g. LiteLLM proxy)
# GATEWAY_VISION_BASE_URL=https://your-proxy.example.com/v1beta
# GATEWAY_VISION_FALLBACK_BACKEND=tesseract  # optional fallback when LLM vision fails
```

The gateway translates OpenAI-format image blocks to Gemini's `inlineData` format.

### Tesseract (Local)

Fast, free, no API key. Runs the `tesseract` CLI locally.

```bash
GATEWAY_VISION_BACKEND=tesseract
GATEWAY_TESSERACT_LANG=eng+chi_sim
```

The Docker image includes `tesseract-ocr` with English and Simplified Chinese language data. To add more languages, install additional `tesseract-ocr-*` packages.

Tesseract extracts **visible text** — it does not describe layouts, colours, or visual context. It is best for:

- Code screenshots, error logs, terminal output
- Documents, forms, receipts
- UI screenshots where the text content is what matters

For photos, diagrams, or UI mockups where layout matters, use `openai_compatible` or `gemini`.

### Fallback

When a remote vision backend (OpenAI-compatible or Gemini) fails, the gateway can automatically retry with a different backend — typically local Tesseract.

```bash
GATEWAY_VISION_FALLBACK_BACKEND=tesseract
```

The fallback applies at runtime for every OCR request. It also applies during [startup warm-up](#openai-compatible): if the primary backend fails the warm-up probe, the gateway retries with the fallback and switches permanently if it succeeds.

Set `GATEWAY_VISION_FALLBACK_BACKEND` to an empty string (or leave it unset) to disable fallback. Currently only `tesseract` is supported as a fallback target.

---

## OCR Cache

OCR results are cached in SQLite (`/data/image_ocr.sqlite3`), keyed by `sha256(image bytes)`. If Cursor re-sends the same image (e.g., across turns), the gateway returns the cached result without calling the vision API.

Advanced cache settings are configured in `config.yaml` (there are no corresponding `GATEWAY_*` environment variables for these):

```yaml
image_ocr_cache_path: /data/image_ocr.sqlite3
image_ocr_cache_max_age_seconds: 2592000 # 30 days
image_ocr_cache_max_rows: 10000
```

---

## Choosing a Backend

| Scenario                             | Recommended Backend                       |
| ------------------------------------ | ----------------------------------------- |
| Code screenshots, logs, terminal     | **tesseract** (fast, extracts exact text) |
| UI mockups, design files, diagrams   | **openai_compatible** (describes layout)  |
| Photos, general images               | **openai_compatible** or **gemini**       |
| Documents with mixed languages       | **tesseract** (100+ languages)            |
| Privacy-sensitive (no external API)  | **tesseract** (runs locally)              |
| Cost-sensitive                       | **tesseract** (free)                      |
| Best understanding of visual content | **openai_compatible** (GPT-4o-mini)       |
