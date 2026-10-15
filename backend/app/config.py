"""Minimal runtime configuration for the local FastAPI service."""

from dataclasses import dataclass
import ipaddress
import math
import os


@dataclass(frozen=True)
class Settings:
    """Settings needed to run the backend foundation locally."""

    host: str = "127.0.0.1"
    port: int = 8000
    pdf_max_bytes: int = 10 * 1024 * 1024
    pdf_max_pages: int = 25
    pdf_max_chars: int = 25_000
    pdf_timeout_seconds: float = 15.0


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def get_settings() -> Settings:
    """Load settings from the environment and enforce loopback binding."""

    host = os.getenv("APP_HOST", "127.0.0.1")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("APP_HOST must be a loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("APP_HOST must be a loopback IP address")

    raw_port = os.getenv("APP_PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("APP_PORT must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("APP_PORT must be an integer from 1 to 65535")

    return Settings(
        host=str(address),
        port=port,
        pdf_max_bytes=_positive_int("PDF_MAX_BYTES", 10 * 1024 * 1024),
        pdf_max_pages=_positive_int("PDF_MAX_PAGES", 25),
        pdf_max_chars=_positive_int("PDF_MAX_CHARS", 25_000),
        pdf_timeout_seconds=_positive_float("PDF_TIMEOUT_SECONDS", 15.0),
    )
