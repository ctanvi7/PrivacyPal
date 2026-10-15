"""Minimal runtime configuration for the local FastAPI service."""

from dataclasses import dataclass
import ipaddress
import os


@dataclass(frozen=True)
class Settings:
    """Settings needed to run the backend foundation locally."""

    host: str = "127.0.0.1"
    port: int = 8000


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

    return Settings(host=str(address), port=port)
