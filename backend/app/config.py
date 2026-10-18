"""Minimal runtime configuration for the local FastAPI service."""

from dataclasses import dataclass, field
from collections.abc import Mapping
import ipaddress
import math
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

BACKEND_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


@dataclass(frozen=True)
class Settings:
    """Settings needed to run the backend foundation locally."""

    host: str = "127.0.0.1"
    deployment_mode: str = "local"
    proxy_token: str = field(default="", repr=False)
    port: int = 8000
    pdf_max_bytes: int = 10 * 1024 * 1024
    pdf_max_pages: int = 25
    pdf_max_chars: int = 25_000
    pdf_timeout_seconds: float = 15.0
    ollama_base_url: str = "http://127.0.0.1:11434"
    gemma_model: str = "gemma4:e4b"
    frontend_origin: str = "http://127.0.0.1:5173"
    model_timeout_seconds: float = 120.0
    ollama_keep_alive_seconds: int = 900
    answer_provider_name: str = "Groq"
    answer_provider_url: str = GROQ_BASE_URL
    answer_provider_model: str = ""
    answer_provider_api_key: str = field(default="", repr=False)
    answer_provider_timeout_seconds: float = 30.0
    sarvam_api_key: str = field(default="", repr=False)
    sarvam_chat_model: str = "sarvam-105b"
    sarvam_translation_model: str = "sarvam-translate:v1"
    sarvam_tts_model: str = "bulbul:v4-flash"
    sarvam_timeout_seconds: float = 45.0
    database_path: str = ""


def _default_database_path() -> Path:
    """Return an OS per-user data path without placing state in the repository."""
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif os.getenv("XDG_DATA_HOME"):
        base = Path(os.environ["XDG_DATA_HOME"])
    else:
        base = Path.home() / ".local" / "share"
    return base / "PrivacyPal" / "conversations.sqlite3"


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw_value = env.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw_value = env.get(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def get_settings() -> Settings:
    """Load backend/.env with process precedence, without mutating os.environ."""

    file_values = dotenv_values(BACKEND_ENV_FILE, interpolate=False, encoding="utf-8-sig")
    env = {**{key: value for key, value in file_values.items() if value is not None}, **os.environ}
    deployment_mode = env.get("DEPLOYMENT_MODE", "local")
    if deployment_mode not in {"local", "aws"}:
        raise ValueError("DEPLOYMENT_MODE must be local or aws")
    proxy_token = env.get("PRIVACYPAL_PROXY_TOKEN", "")
    if deployment_mode == "aws" and len(proxy_token) < 32:
        raise ValueError("AWS mode requires a private proxy token of at least 32 characters")
    host = env.get("APP_HOST", "127.0.0.1")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("APP_HOST must be a loopback IP address") from exc
    if not address.is_loopback and not (deployment_mode == "aws" and str(address) == "0.0.0.0"):
        raise ValueError("APP_HOST must be a loopback IP address")

    raw_port = env.get("APP_PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("APP_PORT must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("APP_PORT must be an integer from 1 to 65535")

    ollama_base_url = env.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    ollama = urlparse(ollama_base_url)
    if ollama.scheme != "http" or ollama.hostname not in {"127.0.0.1", "localhost", "::1"} or ollama.username or ollama.password:
        raise ValueError("OLLAMA_BASE_URL must be a loopback HTTP URL")
    frontend_origin = env.get("FRONTEND_ORIGIN", "http://127.0.0.1:5173")
    origin = urlparse(frontend_origin)
    if origin.scheme != "http" or origin.hostname not in {"127.0.0.1", "localhost", "::1"} or not origin.port or origin.path not in {"", "/"} or origin.username or origin.password:
        raise ValueError("FRONTEND_ORIGIN must be a local HTTP origin with a port")

    provider_name = env.get("ANSWER_PROVIDER_NAME", "Groq").strip()
    provider_url = env.get("ANSWER_PROVIDER_URL", GROQ_BASE_URL).strip().rstrip("/")
    provider_model = env.get("ANSWER_PROVIDER_MODEL", "").strip()
    # Either process credential overrides file credentials, including the alias.
    credentials = os.environ if any(
        name in os.environ for name in ("ANSWER_PROVIDER_API_KEY", "GROQ_API_KEY")
    ) else env
    provider_api_key = (
        credentials.get("ANSWER_PROVIDER_API_KEY", "").strip()
        or credentials.get("GROQ_API_KEY", "").strip()
    )
    if provider_url:
        parsed_provider = urlparse(provider_url)
        if (
            parsed_provider.scheme != "https"
            or not parsed_provider.hostname
            or parsed_provider.username
            or parsed_provider.password
            or parsed_provider.query
            or parsed_provider.fragment
        ):
            raise ValueError("ANSWER_PROVIDER_URL must be an HTTPS base URL or chat/completions endpoint without credentials, query, or fragment")

    configured_database_path = env.get("PRIVACYPAL_DATABASE_PATH", "").strip()
    database_path = Path(configured_database_path or _default_database_path()).expanduser()
    if not database_path.is_absolute():
        raise ValueError("PRIVACYPAL_DATABASE_PATH must be an absolute path")

    return Settings(
        host=str(address),
        deployment_mode=deployment_mode,
        proxy_token=proxy_token,
        port=port,
        pdf_max_bytes=_positive_int(env, "PDF_MAX_BYTES", 10 * 1024 * 1024),
        pdf_max_pages=_positive_int(env, "PDF_MAX_PAGES", 25),
        pdf_max_chars=_positive_int(env, "PDF_MAX_CHARS", 25_000),
        pdf_timeout_seconds=_positive_float(env, "PDF_TIMEOUT_SECONDS", 15.0),
        ollama_base_url=ollama_base_url,
        gemma_model=env.get("GEMMA_MODEL", "gemma4:e4b"),
        frontend_origin=frontend_origin,
        model_timeout_seconds=_positive_float(env, "MODEL_TIMEOUT_SECONDS", 120.0),
        ollama_keep_alive_seconds=_positive_int(env, "OLLAMA_KEEP_ALIVE_SECONDS", 900),
        answer_provider_name=provider_name or "Groq",
        answer_provider_url=provider_url,
        answer_provider_model=provider_model,
        answer_provider_api_key=provider_api_key,
        answer_provider_timeout_seconds=_positive_float(env, "ANSWER_PROVIDER_TIMEOUT_SECONDS", 30.0),
        sarvam_api_key=env.get("SARVAM_API_KEY", "").strip(),
        sarvam_chat_model=env.get("SARVAM_CHAT_MODEL", "sarvam-105b").strip() or "sarvam-105b",
        sarvam_translation_model=env.get("SARVAM_TRANSLATION_MODEL", "sarvam-translate:v1").strip() or "sarvam-translate:v1",
        sarvam_tts_model=env.get("SARVAM_TTS_MODEL", "bulbul:v4-flash").strip() or "bulbul:v4-flash",
        sarvam_timeout_seconds=_positive_float(env, "SARVAM_TIMEOUT_SECONDS", 45.0),
        database_path=str(database_path),
    )
