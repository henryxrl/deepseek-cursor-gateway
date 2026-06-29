from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

APP_DIR_NAME = ".deepseek-cursor-gateway"
CONFIG_FILE_NAME = "config.yaml"
REASONING_CONTENT_FILE_NAME = "reasoning_content.sqlite3"

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}
MISSING = object()

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000
DEFAULT_UPSTREAM_BASE_URL = "https://api.deepseek.com"
DEFAULT_UPSTREAM_MODEL = "deepseek-v4-pro"
DEFAULT_THINKING = "enabled"
DEFAULT_REASONING_EFFORT = "max"
DEFAULT_DISPLAY_REASONING = True
DEFAULT_COLLAPSIBLE_REASONING = True
DEFAULT_NGROK = True
DEFAULT_VERBOSE = False
DEFAULT_REQUEST_TIMEOUT = 300.0
DEFAULT_MAX_REQUEST_BODY_BYTES = 20 * 1024 * 1024
DEFAULT_CORS = False
DEFAULT_MISSING_REASONING_STRATEGY = "recover"
DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
DEFAULT_REASONING_CACHE_MAX_ROWS = 100_000
DEFAULT_USER_MESSAGE_SUFFIX = ""
DEFAULT_UPSTREAM_MAX_INFLIGHT = 2
DEFAULT_UPSTREAM_QUEUE_TIMEOUT_SECONDS = 300
DEFAULT_UPSTREAM_RETRY_ENABLED = True
DEFAULT_UPSTREAM_RETRY_MAX_ATTEMPTS = 3
DEFAULT_UPSTREAM_RETRY_BASE_DELAY_SECONDS = 2.0
DEFAULT_UPSTREAM_RETRY_MAX_DELAY_SECONDS = 30.0
DEFAULT_UPSTREAM_RETRY_JITTER_SECONDS = 1.0
DEFAULT_UPSTREAM_RESPECT_RETRY_AFTER = True
DEFAULT_UPSTREAM_COOLDOWN_ON_429 = True
DEFAULT_IMAGE_HANDLING = "strip"
DEFAULT_VISION_BACKEND = "openai_compatible"
DEFAULT_VISION_MODEL = "gpt-4o-mini"
DEFAULT_VISION_TIMEOUT = 60.0
DEFAULT_VISION_CONCURRENCY = 0
DEFAULT_VISION_WARMUP = "warn"
DEFAULT_VISION_FALLBACK_BACKEND = ""
DEFAULT_TESSERACT_LANG = "eng+chi_sim"
DEFAULT_REQUEST_START_RATE_LIMIT_ENABLED = False
DEFAULT_REQUEST_START_RATE_PER_MINUTE = 0.0
DEFAULT_REQUEST_START_BURST = 0
DEFAULT_IMAGE_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_IMAGE_MAX_COUNT = 10
DEFAULT_IMAGE_MAX_BASE64_BYTES = 50 * 1024 * 1024
DEFAULT_IMAGE_ALLOW_LOCAL_URLS = False
DEFAULT_IMAGE_OCR_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
DEFAULT_IMAGE_OCR_CACHE_MAX_ROWS = 10_000

DEFAULT_CONFIG_HEADER = (
    "# This file was created automatically at ~/.deepseek-cursor-gateway/config.yaml."
)
DEFAULT_CONFIG_TEXT = f"""{DEFAULT_CONFIG_HEADER}
# API keys are read from Cursor's Authorization header and forwarded upstream.

# `model` is the fallback when a request has no model; Cursor's requested
# DeepSeek model name is otherwise respected.
base_url: {DEFAULT_UPSTREAM_BASE_URL}
model: {DEFAULT_UPSTREAM_MODEL}
thinking: {DEFAULT_THINKING}
reasoning_effort: {DEFAULT_REASONING_EFFORT}
display_reasoning: {str(DEFAULT_DISPLAY_REASONING).lower()}
collapsible_reasoning: {str(DEFAULT_COLLAPSIBLE_REASONING).lower()}

host: {DEFAULT_HOST}
port: {DEFAULT_PORT}
ngrok: {str(DEFAULT_NGROK).lower()}
verbose: {str(DEFAULT_VERBOSE).lower()}
request_timeout: {DEFAULT_REQUEST_TIMEOUT:g}
max_request_body_bytes: {DEFAULT_MAX_REQUEST_BODY_BYTES}
cors: {str(DEFAULT_CORS).lower()}

reasoning_content_path: {REASONING_CONTENT_FILE_NAME}
missing_reasoning_strategy: {DEFAULT_MISSING_REASONING_STRATEGY}
reasoning_cache_max_age_seconds: {DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS}
reasoning_cache_max_rows: {DEFAULT_REASONING_CACHE_MAX_ROWS}
user_message_suffix: ""
upstream_max_inflight: {DEFAULT_UPSTREAM_MAX_INFLIGHT}
upstream_queue_timeout_seconds: {DEFAULT_UPSTREAM_QUEUE_TIMEOUT_SECONDS:g}
upstream_retry_enabled: {str(DEFAULT_UPSTREAM_RETRY_ENABLED).lower()}
upstream_retry_max_attempts: {DEFAULT_UPSTREAM_RETRY_MAX_ATTEMPTS}
upstream_retry_base_delay_seconds: {DEFAULT_UPSTREAM_RETRY_BASE_DELAY_SECONDS:g}
upstream_retry_max_delay_seconds: {DEFAULT_UPSTREAM_RETRY_MAX_DELAY_SECONDS:g}
upstream_retry_jitter_seconds: {DEFAULT_UPSTREAM_RETRY_JITTER_SECONDS:g}
upstream_respect_retry_after: {str(DEFAULT_UPSTREAM_RESPECT_RETRY_AFTER).lower()}
upstream_cooldown_on_429: {str(DEFAULT_UPSTREAM_COOLDOWN_ON_429).lower()}
request_start_rate_limit_enabled: {str(DEFAULT_REQUEST_START_RATE_LIMIT_ENABLED).lower()}
request_start_rate_per_minute: {DEFAULT_REQUEST_START_RATE_PER_MINUTE:g}
request_start_burst: {DEFAULT_REQUEST_START_BURST}
image_handling: {DEFAULT_IMAGE_HANDLING}
vision_backend: {DEFAULT_VISION_BACKEND}
# vision_base_url: https://api.openai.com/v1   # uncomment to set
vision_model: {DEFAULT_VISION_MODEL}
# vision_api_key: ""                            # uncomment to set
vision_timeout: {DEFAULT_VISION_TIMEOUT:g}
vision_concurrency: {DEFAULT_VISION_CONCURRENCY}
vision_warmup: {DEFAULT_VISION_WARMUP}
vision_fallback_backend: ""  # optional: tesseract
image_max_bytes: {DEFAULT_IMAGE_MAX_BYTES}
image_max_count: {DEFAULT_IMAGE_MAX_COUNT}
image_max_base64_bytes: {DEFAULT_IMAGE_MAX_BASE64_BYTES}
image_allow_local_urls: {str(DEFAULT_IMAGE_ALLOW_LOCAL_URLS).lower()}
image_ocr_cache_path: image_ocr.sqlite3
image_ocr_cache_max_age_seconds: {DEFAULT_IMAGE_OCR_CACHE_MAX_AGE_SECONDS}
image_ocr_cache_max_rows: {DEFAULT_IMAGE_OCR_CACHE_MAX_ROWS}
"""


def default_app_dir() -> Path:
    return Path.home() / APP_DIR_NAME


def default_config_path() -> Path:
    return default_app_dir() / CONFIG_FILE_NAME


def default_reasoning_content_path() -> Path:
    return default_app_dir() / REASONING_CONTENT_FILE_NAME


def populate_default_config_file(config_path: Path) -> None:
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path.parent.chmod(0o700)
    config_path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    config_path.chmod(0o600)


def load_config_file(config_path: str | Path) -> dict[str, Any]:
    config_path = Path(config_path).expanduser()
    if not config_path.exists():
        return {}

    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML config at {config_path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ValueError(f"Config file must contain a YAML mapping: {config_path}")
    return dict(loaded)


def resolve_config_path(config_path: str | Path | None) -> Path:
    return Path(config_path or default_config_path()).expanduser()


def setting_value(settings: Mapping[str, Any], key: str) -> Any:
    return settings.get(key, MISSING)


def setting_value_any(settings: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = setting_value(settings, key)
        if value is not MISSING:
            return value
    return MISSING


def as_str(value: Any, default: str) -> str:
    if value is MISSING or value is None:
        return default
    return str(value)


def as_optional_str(value: Any) -> str | None:
    if value is MISSING or value is None:
        return None
    stripped = str(value).strip()
    return stripped if stripped else None


def as_bool(value: Any, default: bool) -> bool:
    if value is MISSING or value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def as_int(value: Any, default: int) -> int:
    if value is MISSING or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float) -> float:
    if value is MISSING or value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_path(value: Any, default_path: Path, relative_base: Path) -> Path:
    if value is MISSING or value is None or value == "":
        return default_path
    candidate_path = Path(str(value)).expanduser()
    if candidate_path.is_absolute():
        return candidate_path
    return relative_base / candidate_path


def settings_from_config(
    config_path: str | Path | None,
) -> tuple[dict[str, Any], Path]:
    resolved_config_path = resolve_config_path(config_path)
    if config_path is None and not resolved_config_path.exists():
        populate_default_config_file(resolved_config_path)
    return load_config_file(resolved_config_path), resolved_config_path


def normalize_thinking(value: Any) -> str:
    thinking = as_str(value, DEFAULT_THINKING).strip().lower()
    if thinking in {"enabled", "disabled"}:
        return thinking
    return DEFAULT_THINKING


def normalize_missing_reasoning_strategy(value: Any) -> str:
    strategy = as_str(value, DEFAULT_MISSING_REASONING_STRATEGY).strip().lower()
    if strategy in {"recover", "reject"}:
        return strategy
    return DEFAULT_MISSING_REASONING_STRATEGY


def normalize_image_handling(value: Any) -> str:
    handling = as_str(value, DEFAULT_IMAGE_HANDLING).strip().lower()
    if handling in {"strip", "reject", "ocr"}:
        return handling
    return DEFAULT_IMAGE_HANDLING


def normalize_vision_warmup(value: Any) -> str:
    mode = as_str(value, DEFAULT_VISION_WARMUP).strip().lower()
    if mode in {"off", "warn", "require"}:
        return mode
    return DEFAULT_VISION_WARMUP


def normalize_vision_fallback_backend(value: Any) -> str:
    backend = as_str(value, DEFAULT_VISION_FALLBACK_BACKEND).strip().lower()
    if backend in {"", "none", "off"}:
        return ""
    if backend == "tesseract":
        return backend
    return DEFAULT_VISION_FALLBACK_BACKEND


@dataclass(frozen=True)
class GatewayConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    upstream_base_url: str = DEFAULT_UPSTREAM_BASE_URL
    upstream_model: str = DEFAULT_UPSTREAM_MODEL
    thinking: str = DEFAULT_THINKING
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES
    reasoning_content_path: Path = field(default_factory=default_reasoning_content_path)
    missing_reasoning_strategy: str = DEFAULT_MISSING_REASONING_STRATEGY
    reasoning_cache_max_age_seconds: int = DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS
    reasoning_cache_max_rows: int = DEFAULT_REASONING_CACHE_MAX_ROWS
    display_reasoning: bool = DEFAULT_DISPLAY_REASONING
    collapsible_reasoning: bool = DEFAULT_COLLAPSIBLE_REASONING
    cors: bool = DEFAULT_CORS
    verbose: bool = DEFAULT_VERBOSE
    ngrok: bool = DEFAULT_NGROK
    ngrok_url: str | None = None
    trace_dir: Path | None = None
    user_message_suffix: str = DEFAULT_USER_MESSAGE_SUFFIX
    upstream_max_inflight: int = DEFAULT_UPSTREAM_MAX_INFLIGHT
    upstream_queue_timeout_seconds: float = DEFAULT_UPSTREAM_QUEUE_TIMEOUT_SECONDS
    upstream_retry_enabled: bool = DEFAULT_UPSTREAM_RETRY_ENABLED
    upstream_retry_max_attempts: int = DEFAULT_UPSTREAM_RETRY_MAX_ATTEMPTS
    upstream_retry_base_delay_seconds: float = DEFAULT_UPSTREAM_RETRY_BASE_DELAY_SECONDS
    upstream_retry_max_delay_seconds: float = DEFAULT_UPSTREAM_RETRY_MAX_DELAY_SECONDS
    upstream_retry_jitter_seconds: float = DEFAULT_UPSTREAM_RETRY_JITTER_SECONDS
    upstream_respect_retry_after: bool = DEFAULT_UPSTREAM_RESPECT_RETRY_AFTER
    upstream_cooldown_on_429: bool = DEFAULT_UPSTREAM_COOLDOWN_ON_429
    image_handling: str = DEFAULT_IMAGE_HANDLING
    vision_backend: str = DEFAULT_VISION_BACKEND
    vision_base_url: str | None = None
    vision_model: str = DEFAULT_VISION_MODEL
    vision_api_key: str = ""
    vision_timeout: float = DEFAULT_VISION_TIMEOUT
    vision_concurrency: int = DEFAULT_VISION_CONCURRENCY
    vision_warmup: str = DEFAULT_VISION_WARMUP
    vision_fallback_backend: str = DEFAULT_VISION_FALLBACK_BACKEND
    tesseract_lang: str = DEFAULT_TESSERACT_LANG
    request_start_rate_limit_enabled: bool = DEFAULT_REQUEST_START_RATE_LIMIT_ENABLED
    request_start_rate_per_minute: float = DEFAULT_REQUEST_START_RATE_PER_MINUTE
    request_start_burst: int = DEFAULT_REQUEST_START_BURST
    image_max_bytes: int = DEFAULT_IMAGE_MAX_BYTES
    image_max_count: int = DEFAULT_IMAGE_MAX_COUNT
    image_max_base64_bytes: int = DEFAULT_IMAGE_MAX_BASE64_BYTES
    image_allow_local_urls: bool = DEFAULT_IMAGE_ALLOW_LOCAL_URLS
    image_ocr_cache_path: Path = field(default_factory=Path)
    image_ocr_cache_max_age_seconds: int = DEFAULT_IMAGE_OCR_CACHE_MAX_AGE_SECONDS
    image_ocr_cache_max_rows: int = DEFAULT_IMAGE_OCR_CACHE_MAX_ROWS

    @classmethod
    def from_file(
        cls: type[GatewayConfig],
        config_path: str | Path | None = None,
    ) -> "GatewayConfig":
        settings, resolved_config_path = settings_from_config(config_path)
        config_dir = resolved_config_path.parent

        return cls(
            host=as_str(
                setting_value(settings, "host"),
                DEFAULT_HOST,
            ),
            port=as_int(
                setting_value(settings, "port"),
                DEFAULT_PORT,
            ),
            upstream_base_url=as_str(
                setting_value(settings, "base_url"),
                DEFAULT_UPSTREAM_BASE_URL,
            ).rstrip("/"),
            upstream_model=as_str(
                setting_value(settings, "model"),
                DEFAULT_UPSTREAM_MODEL,
            ),
            thinking=normalize_thinking(setting_value(settings, "thinking")),
            reasoning_effort=as_str(
                setting_value(settings, "reasoning_effort"),
                DEFAULT_REASONING_EFFORT,
            ),
            request_timeout=as_float(
                setting_value(settings, "request_timeout"),
                DEFAULT_REQUEST_TIMEOUT,
            ),
            max_request_body_bytes=as_int(
                setting_value(settings, "max_request_body_bytes"),
                DEFAULT_MAX_REQUEST_BODY_BYTES,
            ),
            reasoning_content_path=as_path(
                setting_value(settings, "reasoning_content_path"),
                default_reasoning_content_path(),
                config_dir,
            ),
            missing_reasoning_strategy=normalize_missing_reasoning_strategy(
                setting_value(settings, "missing_reasoning_strategy")
            ),
            reasoning_cache_max_age_seconds=as_int(
                setting_value(settings, "reasoning_cache_max_age_seconds"),
                DEFAULT_REASONING_CACHE_MAX_AGE_SECONDS,
            ),
            reasoning_cache_max_rows=as_int(
                setting_value(settings, "reasoning_cache_max_rows"),
                DEFAULT_REASONING_CACHE_MAX_ROWS,
            ),
            display_reasoning=as_bool(
                setting_value(settings, "display_reasoning"),
                DEFAULT_DISPLAY_REASONING,
            ),
            collapsible_reasoning=as_bool(
                setting_value_any(
                    settings,
                    "collasible_reasoning",
                    "collapsible_reasoning",
                ),
                DEFAULT_COLLAPSIBLE_REASONING,
            ),
            cors=as_bool(
                setting_value(settings, "cors"),
                DEFAULT_CORS,
            ),
            verbose=as_bool(
                setting_value(settings, "verbose"),
                DEFAULT_VERBOSE,
            ),
            ngrok=as_bool(
                setting_value(settings, "ngrok"),
                DEFAULT_NGROK,
            ),
            ngrok_url=as_optional_str(setting_value(settings, "ngrok_url")),
            user_message_suffix=as_str(
                setting_value(settings, "user_message_suffix"),
                DEFAULT_USER_MESSAGE_SUFFIX,
            ),
            upstream_max_inflight=as_int(
                setting_value(settings, "upstream_max_inflight"),
                DEFAULT_UPSTREAM_MAX_INFLIGHT,
            ),
            upstream_queue_timeout_seconds=as_float(
                setting_value(settings, "upstream_queue_timeout_seconds"),
                DEFAULT_UPSTREAM_QUEUE_TIMEOUT_SECONDS,
            ),
            upstream_retry_enabled=as_bool(
                setting_value(settings, "upstream_retry_enabled"),
                DEFAULT_UPSTREAM_RETRY_ENABLED,
            ),
            upstream_retry_max_attempts=as_int(
                setting_value(settings, "upstream_retry_max_attempts"),
                DEFAULT_UPSTREAM_RETRY_MAX_ATTEMPTS,
            ),
            upstream_retry_base_delay_seconds=as_float(
                setting_value(settings, "upstream_retry_base_delay_seconds"),
                DEFAULT_UPSTREAM_RETRY_BASE_DELAY_SECONDS,
            ),
            upstream_retry_max_delay_seconds=as_float(
                setting_value(settings, "upstream_retry_max_delay_seconds"),
                DEFAULT_UPSTREAM_RETRY_MAX_DELAY_SECONDS,
            ),
            upstream_retry_jitter_seconds=as_float(
                setting_value(settings, "upstream_retry_jitter_seconds"),
                DEFAULT_UPSTREAM_RETRY_JITTER_SECONDS,
            ),
            upstream_respect_retry_after=as_bool(
                setting_value(settings, "upstream_respect_retry_after"),
                DEFAULT_UPSTREAM_RESPECT_RETRY_AFTER,
            ),
            upstream_cooldown_on_429=as_bool(
                setting_value(settings, "upstream_cooldown_on_429"),
                DEFAULT_UPSTREAM_COOLDOWN_ON_429,
            ),
            image_handling=normalize_image_handling(
                setting_value(settings, "image_handling")
            ),
            vision_backend=as_str(
                setting_value(settings, "vision_backend"),
                DEFAULT_VISION_BACKEND,
            ),
            vision_base_url=(
                as_optional_str(setting_value(settings, "vision_base_url"))
            ),
            vision_model=as_str(
                setting_value(settings, "vision_model"),
                DEFAULT_VISION_MODEL,
            ),
            vision_api_key=as_str(setting_value(settings, "vision_api_key"), ""),
            vision_timeout=as_float(
                setting_value(settings, "vision_timeout"),
                DEFAULT_VISION_TIMEOUT,
            ),
            vision_concurrency=as_int(
                setting_value(settings, "vision_concurrency"),
                DEFAULT_VISION_CONCURRENCY,
            ),
            vision_warmup=normalize_vision_warmup(
                setting_value(settings, "vision_warmup")
            ),
            vision_fallback_backend=normalize_vision_fallback_backend(
                setting_value(settings, "vision_fallback_backend")
            ),
            tesseract_lang=as_str(
                setting_value(settings, "tesseract_lang"),
                DEFAULT_TESSERACT_LANG,
            ),
            image_max_bytes=as_int(
                setting_value(settings, "image_max_bytes"),
                DEFAULT_IMAGE_MAX_BYTES,
            ),
            image_max_count=as_int(
                setting_value(settings, "image_max_count"),
                DEFAULT_IMAGE_MAX_COUNT,
            ),
            image_max_base64_bytes=as_int(
                setting_value(settings, "image_max_base64_bytes"),
                DEFAULT_IMAGE_MAX_BASE64_BYTES,
            ),
            image_allow_local_urls=as_bool(
                setting_value(settings, "image_allow_local_urls"),
                DEFAULT_IMAGE_ALLOW_LOCAL_URLS,
            ),
            image_ocr_cache_path=as_path(
                setting_value(settings, "image_ocr_cache_path"),
                Path("image_ocr.sqlite3"),
                config_dir,
            ),
            image_ocr_cache_max_age_seconds=as_int(
                setting_value(settings, "image_ocr_cache_max_age_seconds"),
                DEFAULT_IMAGE_OCR_CACHE_MAX_AGE_SECONDS,
            ),
            image_ocr_cache_max_rows=as_int(
                setting_value(settings, "image_ocr_cache_max_rows"),
                DEFAULT_IMAGE_OCR_CACHE_MAX_ROWS,
            ),
            request_start_rate_limit_enabled=as_bool(
                setting_value(settings, "request_start_rate_limit_enabled"),
                DEFAULT_REQUEST_START_RATE_LIMIT_ENABLED,
            ),
            request_start_rate_per_minute=as_float(
                setting_value(settings, "request_start_rate_per_minute"),
                DEFAULT_REQUEST_START_RATE_PER_MINUTE,
            ),
            request_start_burst=as_int(
                setting_value(settings, "request_start_burst"),
                DEFAULT_REQUEST_START_BURST,
            ),
        )
