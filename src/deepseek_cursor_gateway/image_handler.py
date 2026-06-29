from __future__ import annotations

import base64
import copy
import hashlib
import ipaddress
import json
import os
import re
import sqlite3
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .logging import LOG

# ---------------------------------------------------------------------------
# Image detection
# ---------------------------------------------------------------------------


class ImageInputRejected(Exception):
    """Raised when image input is detected and image_handling is 'reject'."""

    def __init__(self, image_count: int) -> None:
        self.image_count = image_count
        super().__init__(
            f"Image input was detected ({image_count} image block(s)), "
            "but image handling is set to 'reject'. "
            "Set image_handling=strip or image_handling=ocr."
        )


def count_image_blocks(messages: Any) -> int:
    """Return the number of image_url blocks found in the message list."""
    if not isinstance(messages, list):
        return 0
    total = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if content is None or isinstance(content, str):
            continue
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    total += 1
    return total


# ---------------------------------------------------------------------------
# OCR exceptions
# ---------------------------------------------------------------------------


class ImageSecurityViolation(Exception):
    """Raised when an image URL fails security checks (scheme, SSRF, MIME)."""


class ImageTooLarge(Exception):
    """Raised when an image exceeds the configured size limit."""


class OcrError(Exception):
    """Raised when the vision backend fails to produce a description."""


# ---------------------------------------------------------------------------
# OCR cache (SQLite)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OcrCacheConfig:
    path: Path
    max_age_seconds: int = 30 * 24 * 3600  # 30 days
    max_rows: int = 10_000


class OcrCache:
    """SQLite-backed cache for vision model OCR results, keyed by sha256."""

    def __init__(self, config: OcrCacheConfig) -> None:
        self._config = config
        config.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(config.path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS image_ocr_cache ("
            "  key TEXT PRIMARY KEY,"
            "  summary TEXT NOT NULL,"
            "  created_at REAL NOT NULL"
            ")"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ocr_created_at "
            "ON image_ocr_cache(created_at)"
        )
        self._conn.commit()

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT summary FROM image_ocr_cache WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row is not None else None

    def put(self, key: str, summary: str) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO image_ocr_cache (key, summary, created_at) "
                "VALUES (?, ?, ?)",
                (key, summary, now),
            )
            self._conn.commit()
            self._prune_locked()

    def _prune_locked(self) -> None:
        cutoff = time.time() - self._config.max_age_seconds
        self._conn.execute(
            "DELETE FROM image_ocr_cache WHERE created_at < ?", (cutoff,)
        )
        row_count = self._conn.execute(
            "SELECT COUNT(*) FROM image_ocr_cache"
        ).fetchone()[0]
        excess = row_count - self._config.max_rows
        if excess > 0:
            self._conn.execute(
                "DELETE FROM image_ocr_cache WHERE key IN ("
                "  SELECT key FROM image_ocr_cache "
                "  ORDER BY created_at ASC LIMIT ?"
                ")",
                (excess,),
            )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# Security validators
# ---------------------------------------------------------------------------

_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_ALLOWED_SCHEMES = {"https"}
_ALLOWED_MIMES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

_BASE64_DATA_RE = re.compile(r"^data:([^;]+);base64,", re.IGNORECASE)

OCR_REPLACEMENT_PREFIX = "[Image attachment converted by gateway]"
OCR_TRACE_OMITTED = "[OCR summary omitted from trace]"
IMAGE_URL_TRACE_OMITTED = "[image_url omitted from trace]"


def _validate_address(hostname: str, address: str, allow_local: bool) -> None:
    try:
        addr = ipaddress.ip_address(address)
    except ValueError:
        raise ImageSecurityViolation(f"Invalid resolved IP: {address}") from None
    if allow_local and addr.is_loopback:
        return
    for net in _PRIVATE_RANGES:
        if addr in net:
            raise ImageSecurityViolation(
                f"Blocked private IP for {hostname}: {address}"
            )


def _validate_url(url: str, allow_local: bool) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES and not (
        allow_local and parsed.scheme == "http"
    ):
        raise ImageSecurityViolation(f"Blocked URL scheme: {parsed.scheme or '(none)'}")
    hostname = parsed.hostname
    if hostname is None:
        raise ImageSecurityViolation("URL has no resolvable hostname")
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ImageSecurityViolation(
                f"Failed to resolve image host: {hostname}"
            ) from exc
        addresses = {info[4][0] for info in infos}
        if not addresses:
            raise ImageSecurityViolation(f"Failed to resolve image host: {hostname}")
        for address in addresses:
            _validate_address(hostname, address, allow_local)
        return
    _validate_address(hostname, str(addr), allow_local)


def _validate_mime(
    content_type: str | None,
    allowed_mimes: frozenset[str] = _ALLOWED_MIMES,
) -> None:
    if content_type is None:
        raise ImageSecurityViolation("Missing Content-Type in image response")
    mime = content_type.split(";")[0].strip().lower()
    if mime not in allowed_mimes:
        raise ImageSecurityViolation(f"Blocked MIME type: {mime}")


def _detect_image_mime(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if (
        len(image_bytes) >= 12
        and image_bytes.startswith(b"RIFF")
        and image_bytes[8:12] == b"WEBP"
    ):
        return "image/webp"
    return "image/png"


def _http_error_detail(exc: HTTPError, max_chars: int = 1000) -> str:
    try:
        body = exc.read(max_chars + 1)
    except Exception:
        return ""
    text = body.decode("utf-8", "replace").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text


# ---------------------------------------------------------------------------
# Image fetching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecurityConfig:
    max_bytes: int = 20 * 1024 * 1024
    max_count: int = 10
    max_base64_bytes: int = 50 * 1024 * 1024
    allowed_mimes: frozenset[str] = _ALLOWED_MIMES
    allow_local_urls: bool = False


def _extract_image_parts(
    messages: list[dict[str, Any]],
) -> list[tuple[int, int, dict[str, Any]]]:
    """Yield (msg_idx, part_idx, image_url_part) for every image block."""
    result: list[tuple[int, int, dict[str, Any]]] = []
    for mi, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for pi, part in enumerate(content):
            if isinstance(part, dict) and part.get("type") == "image_url":
                result.append((mi, pi, part))
    return result


def _fetch_image_bytes(image_url: dict[str, Any], security: SecurityConfig) -> bytes:
    """Resolve an image_url block to raw bytes, enforcing security limits."""
    url = image_url.get("url", "")
    if isinstance(url, str) and url.startswith("data:"):
        return _decode_base64_data_url(url, security)
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        return _fetch_remote_image(url, security)
    raise ImageSecurityViolation(f"Unsupported image_url value: {url!r}")


def _decode_base64_data_url(data_url: str, security: SecurityConfig) -> bytes:
    m = _BASE64_DATA_RE.match(data_url)
    if not m:
        raise ImageSecurityViolation("Invalid data URL format")
    _validate_mime(m.group(1), security.allowed_mimes)
    b64 = data_url[m.end() :]
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        raise ImageSecurityViolation("Invalid base64 in data URL")
    if len(raw) > security.max_bytes:
        raise ImageTooLarge(
            f"Base64 image is {len(raw)} bytes, max {security.max_bytes}"
        )
    return raw


def _fetch_remote_image(url: str, security: SecurityConfig) -> bytes:
    _validate_url(url, security.allow_local_urls)
    try:
        with urlopen(Request(url, method="GET"), timeout=30) as resp:
            content_type = resp.headers.get("Content-Type")
            _validate_mime(content_type, security.allowed_mimes)
            data = resp.read(security.max_bytes + 1)
    except HTTPError as exc:
        raise ImageSecurityViolation(f"HTTP {exc.code} fetching image: {url}")
    except URLError as exc:
        raise ImageSecurityViolation(f"Failed to fetch image: {exc.reason}")
    if len(data) > security.max_bytes:
        raise ImageTooLarge(
            f"Remote image is {len(data)} bytes, max {security.max_bytes}"
        )
    return data


# ---------------------------------------------------------------------------
# Vision backends
# ---------------------------------------------------------------------------
# The gateway supports two remote vision backends (openai_compatible, gemini)
# and one local backend (tesseract).


@dataclass(frozen=True)
class VisionConfig:
    backend: str  # "openai_compatible", "gemini", or "tesseract"
    base_url: str | None = None
    model: str = "gpt-4o-mini"
    api_key: str = ""
    timeout: float = 60.0
    concurrency: int = 0  # 0 = unlimited, >0 = max concurrent vision API calls
    fallback_backend: str = ""  # currently supports "tesseract"
    tesseract_lang: str = "eng+chi_sim"  # only used when backend == "tesseract"


_VISION_WARMUP_IMAGE_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAGklEQVR42mP4TyJgGOQaGHCAUQ301TBE0xIAxII939o0tJoAAAAASUVORK5CYII="
)


# Module-level semaphore for limiting concurrent vision API calls across all
# request handlers.  Initialised once by the server via init_vision_concurrency().
_vision_semaphore: threading.BoundedSemaphore | None = None


def init_vision_concurrency(max_concurrent: int) -> None:
    """Initialise (or re-initialise) the global vision concurrency semaphore.

    A value of 0 disables concurrency control (unlimited parallel vision calls).
    """
    global _vision_semaphore
    if max_concurrent > 0:
        _vision_semaphore = threading.BoundedSemaphore(max_concurrent)
    else:
        _vision_semaphore = None


def _describe_image(
    image_bytes: bytes,
    vision: VisionConfig,
    ocr_cache: OcrCache | None,
) -> str:
    """Return a text description of *image_bytes*, using the cache if available."""
    key = hashlib.sha256(image_bytes).hexdigest()
    if ocr_cache is not None:
        cached = ocr_cache.get(key)
        if cached is not None:
            LOG.info("ocr cache hit key=%s", key[:12])
            return cached

    LOG.info("ocr calling vision model=%s backend=%s", vision.model, vision.backend)
    acquired = False
    if _vision_semaphore is not None:
        _vision_semaphore.acquire()
        acquired = True
    try:
        try:
            summary = _call_vision_backend(image_bytes, vision)
        except OcrError as exc:
            fallback_backend = vision.fallback_backend.strip().lower()
            if not fallback_backend or fallback_backend == vision.backend:
                raise
            LOG.warning(
                "ocr primary backend failed backend=%s fallback=%s reason=%s",
                vision.backend,
                fallback_backend,
                exc,
            )
            fallback_vision = replace(
                vision,
                backend=fallback_backend,
                fallback_backend="",
            )
            summary = _call_vision_backend(image_bytes, fallback_vision)
            LOG.warning("ocr fallback succeeded backend=%s", fallback_backend)
    finally:
        if acquired:
            _vision_semaphore.release()

    if ocr_cache is not None:
        ocr_cache.put(key, summary)
        LOG.info("ocr cache store key=%s", key[:12])
    return summary


def warm_up_vision_backend(vision: VisionConfig) -> str:
    """Run a tiny vision request to verify that the configured backend responds."""
    summary = _describe_image(_VISION_WARMUP_IMAGE_BYTES, vision, ocr_cache=None)
    if not summary.strip():
        raise OcrError("Vision warm-up returned an empty response")
    return summary


def _call_vision_backend(image_bytes: bytes, vision: VisionConfig) -> str:
    if vision.backend == "openai_compatible":
        return _call_openai_vision(image_bytes, vision)
    if vision.backend == "gemini":
        return _call_gemini_vision(image_bytes, vision)
    if vision.backend == "tesseract":
        return _call_tesseract_ocr(image_bytes, vision)
    raise OcrError(f"Unknown vision backend: {vision.backend}")


def _openai_token_limit_key(model: str) -> str:
    model_id = str(model or "").strip().lower().rsplit("/", 1)[-1]
    if model_id.startswith(("gpt-5", "o1", "o3", "o4")):
        return "max_completion_tokens"
    return "max_tokens"


def _call_openai_vision(image_bytes: bytes, vision: VisionConfig) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    mime_type = _detect_image_mime(image_bytes)
    token_limit_key = _openai_token_limit_key(vision.model)
    body = json.dumps(
        {
            "model": vision.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Describe this image in detail. "
                                "Include any visible text, UI elements, code, "
                                "diagrams, or screenshots. Be concise but thorough."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                        },
                    ],
                }
            ],
            token_limit_key: 1024,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    base = (vision.base_url or "https://api.openai.com/v1").rstrip("/")
    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {vision.api_key}",
        "Content-Type": "application/json",
    }

    try:
        with urlopen(
            Request(url, data=body, headers=headers, method="POST"),
            timeout=vision.timeout,
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _http_error_detail(exc)
        message = f"Vision API returned {exc.code}"
        if detail:
            message = f"{message}: {detail}"
        raise OcrError(message) from exc
    except URLError as exc:
        raise OcrError(f"Vision API unreachable: {exc.reason}") from exc

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise OcrError("Unexpected vision API response structure")
    return str(content).strip()


def _call_gemini_vision(image_bytes: bytes, vision: VisionConfig) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    mime_type = _detect_image_mime(image_bytes)
    body = json.dumps(
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": "Describe this image in detail. Include any visible text, UI elements, code, diagrams, or screenshots. Be concise but thorough."
                        },
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": b64,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"maxOutputTokens": 1024},
        },
        ensure_ascii=False,
    ).encode("utf-8")

    model = vision.model or "gemini-2.0-flash"
    base = (
        vision.base_url or "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    url = f"{base}/models/{model}:generateContent?key={vision.api_key}"
    headers = {"Content-Type": "application/json"}

    try:
        with urlopen(
            Request(url, data=body, headers=headers, method="POST"),
            timeout=vision.timeout,
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _http_error_detail(exc)
        message = f"Gemini API returned {exc.code}"
        if detail:
            message = f"{message}: {detail}"
        raise OcrError(message) from exc
    except URLError as exc:
        raise OcrError(f"Gemini API unreachable: {exc.reason}") from exc

    try:
        content = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise OcrError("Unexpected Gemini API response structure")
    return str(content).strip()


def _call_tesseract_ocr(image_bytes: bytes, vision: VisionConfig) -> str:
    """Run Tesseract OCR locally via subprocess on *image_bytes*."""
    LOG.info("tesseract ocr starting lang=%s", vision.tesseract_lang)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["tesseract", tmp_path, "stdout", "-l", vision.tesseract_lang],
            capture_output=True,
            text=True,
            timeout=vision.timeout,
            check=True,
        )
    except FileNotFoundError:
        raise OcrError(
            "Tesseract is not installed. Install tesseract-ocr to use backend=tesseract."
        )
    except subprocess.TimeoutExpired:
        raise OcrError(f"Tesseract timed out after {vision.timeout:.0f}s")
    except subprocess.CalledProcessError as exc:
        raise OcrError(
            f"Tesseract exited with code {exc.returncode}: {exc.stderr.strip()}"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    text = result.stdout.strip()
    if not text:
        LOG.info("tesseract ocr complete (no text detected)")
        return "(no text detected in image)"
    LOG.info("tesseract ocr complete chars=%d", len(text))
    return text


# ---------------------------------------------------------------------------
# OCR pipeline
# ---------------------------------------------------------------------------
#
# run_ocr_pipeline() is the main entry point: it replaces all image_url
# blocks in a chat-completion payload with OCR text summaries.

OCR_REPLACEMENT_TEMPLATE = (
    OCR_REPLACEMENT_PREFIX + "\n\nOCR / visual summary:\n{summary}"
)


def sanitize_image_payload_for_trace(payload: Any) -> Any:
    """Return a copy with image URLs, base64 bytes, and OCR summaries omitted."""
    if not isinstance(payload, dict):
        return payload
    sanitized = copy.deepcopy(payload)
    messages = sanitized.get("messages")
    if not isinstance(messages, list):
        return sanitized
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = _sanitize_ocr_text(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "image_url":
                    replacement: dict[str, Any] = {"url": IMAGE_URL_TRACE_OMITTED}
                    image_url = part.get("image_url")
                    if (
                        isinstance(image_url, dict)
                        and image_url.get("detail") is not None
                    ):
                        replacement["detail"] = image_url["detail"]
                    part["image_url"] = replacement
                elif isinstance(part.get("text"), str):
                    part["text"] = _sanitize_ocr_text(part["text"])
    return sanitized


def _sanitize_ocr_text(text: str) -> str:
    if OCR_REPLACEMENT_PREFIX not in text:
        return text
    prefix, _marker, _tail = text.partition(OCR_REPLACEMENT_PREFIX)
    return prefix + OCR_TRACE_OMITTED


def run_ocr_pipeline(
    payload: dict[str, Any],
    vision: VisionConfig,
    ocr_cache: OcrCache | None,
    security: SecurityConfig,
) -> int:
    """Replace all image_url blocks in *payload* with OCR text summaries.

    Modifies payload["messages"] in place.  Returns the number of images
    that were successfully converted.

    Raises ImageSecurityViolation, ImageTooLarge, or OcrError on failure.
    """
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return 0

    image_parts = _extract_image_parts(messages)
    if not image_parts:
        return 0

    if len(image_parts) > security.max_count:
        raise ImageSecurityViolation(
            f"Too many images: {len(image_parts)} (max {security.max_count})"
        )

    # Validate cumulative base64 size
    total_base64 = 0
    for _, _, part in image_parts:
        url = part["image_url"].get("url", "")
        if isinstance(url, str) and url.startswith("data:"):
            total_base64 += len(url)
    if total_base64 > security.max_base64_bytes:
        raise ImageTooLarge(
            f"Total base64 image data is {total_base64} bytes, "
            f"max {security.max_base64_bytes}"
        )

    converted = 0
    for mi, pi, part in image_parts:
        image_bytes = _fetch_image_bytes(part["image_url"], security)
        summary = _describe_image(image_bytes, vision, ocr_cache)
        text_block = OCR_REPLACEMENT_TEMPLATE.format(summary=summary)
        messages[mi]["content"][pi] = {"type": "text", "text": text_block}
        converted += 1

    return converted
