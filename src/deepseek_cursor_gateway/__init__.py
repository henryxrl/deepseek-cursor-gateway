"""Local OpenAI-compatible gateway for DeepSeek thinking models."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

__all__ = ["__version__"]


def _read_version() -> str:
    try:
        return version("deepseek-cursor-gateway")
    except PackageNotFoundError:
        version_file = Path(__file__).resolve().parents[2] / "VERSION"
        if version_file.is_file():
            return version_file.read_text(encoding="utf-8").strip()
        return "0.0.0"


__version__ = _read_version()
