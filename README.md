<h1 align="center"><img src="assets/logo.png" width="150" alt="logo"><br>DeepSeek Cursor Gateway</h1>

<p align="center"><strong>Docker-first gateway for Cursor + DeepSeek</strong></p>
<p align="center">
  Forked from
  <a href="https://github.com/abcduyt1243-git/deepseek-cursor-proxy-turbo">abcduyt1243-git/deepseek-cursor-proxy-turbo</a>,
  based on
  <a href="https://github.com/yxlao/deepseek-cursor-proxy">yxlao/deepseek-cursor-proxy</a>.
</p>

---

A local gateway that makes [Cursor](https://cursor.com) work with [DeepSeek V4](https://api-docs.deepseek.com) models, with Docker packaging, traffic control, and image/OCR handling.

**What it does:**

- **Reasoning-content cache** — preserves DeepSeek's `reasoning_content` across Cursor turns so tool-call reasoning chains never break.
- **Upstream traffic control** — concurrency gate, queue timeout, automatic retry with exponential backoff, `Retry-After` support, and global 429 cooldown.
- **Image input handling** — strip, reject, or OCR images before forwarding to DeepSeek. Supports OpenAI-compatible vision models, Google Gemini, and local Tesseract OCR.

---

## Quick Start

```bash
cp .env.example .env
# edit .env with your configuration
docker compose up -d
```

Set Cursor's API Base URL to `http://localhost:9000/v1`.

Your DeepSeek API key stays in Cursor — the gateway forwards it transparently.

---

## Documentation

- [Feature overview →](docs/README.md)
- [Configuration reference →](docs/configuration.md)
- [Upstream traffic control →](docs/rate-limiting.md)
- [Image handling and OCR →](docs/image-handling.md)
- [Deployment guide →](docs/deployment.md)

---

## From Source (without Docker)

```bash
git clone https://github.com/henryxrl/deepseek-cursor-gateway.git
cd deepseek-cursor-gateway
pip install -e .
deepseek-cursor-gateway --host 0.0.0.0 --port 9000
```

---

## Attribution

This project is a fork of [abcduyt1243-git/deepseek-cursor-proxy-turbo](https://github.com/abcduyt1243-git/deepseek-cursor-proxy-turbo), which itself builds on [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy) by Yixing Lao.

See [UPSTREAM_README.md](UPSTREAM_README.md) for the original README.

## License

MIT — same as the upstream projects. See [LICENSE](LICENSE).
