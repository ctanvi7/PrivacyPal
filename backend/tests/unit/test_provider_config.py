"""Synthetic settings only; never read developer credentials in these tests."""

from pathlib import Path

import pytest

import app.config as config


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    # Isolate both provider aliases and the remaining backend settings.
    for name in (
        "APP_HOST", "APP_PORT", "DEPLOYMENT_MODE", "PRIVACYPAL_PROXY_TOKEN", "FRONTEND_ORIGIN", "OLLAMA_BASE_URL", "GEMMA_MODEL",
        "PDF_MAX_BYTES", "PDF_MAX_PAGES", "PDF_MAX_CHARS", "PDF_TIMEOUT_SECONDS",
        "MODEL_TIMEOUT_SECONDS", "OLLAMA_KEEP_ALIVE_SECONDS", "ANSWER_PROVIDER_NAME", "ANSWER_PROVIDER_URL",
        "ANSWER_PROVIDER_MODEL", "ANSWER_PROVIDER_API_KEY", "GROQ_API_KEY",
        "ANSWER_PROVIDER_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "BACKEND_ENV_FILE", path)
    return path


def test_env_path_is_backend_relative():
    assert config.BACKEND_ENV_FILE == Path(config.__file__).resolve().parents[1] / ".env"


def test_local_file_loads_from_any_working_directory_and_refreshes(env_file, tmp_path, monkeypatch):
    env_file.write_text('ANSWER_PROVIDER_MODEL="chosen-test-model"\nGROQ_API_KEY=synthetic-file-key\n')
    monkeypatch.chdir(tmp_path.parent)
    settings = config.get_settings()
    assert settings.answer_provider_url == "https://api.groq.com/openai/v1"
    assert settings.answer_provider_name == "Groq"
    assert settings.answer_provider_model == "chosen-test-model"
    assert settings.answer_provider_api_key == "synthetic-file-key"
    assert "synthetic-file-key" not in repr(settings)
    env_file.write_text('ANSWER_PROVIDER_MODEL=updated-test-model\nGROQ_API_KEY=updated-synthetic-key\n')
    assert config.get_settings().answer_provider_model == "updated-test-model"
    assert config.get_settings().answer_provider_api_key == "updated-synthetic-key"


@pytest.mark.parametrize("key_name", ["ANSWER_PROVIDER_API_KEY", "GROQ_API_KEY"])
def test_process_values_override_file_even_across_key_aliases(env_file, monkeypatch, key_name):
    env_file.write_text(
        "ANSWER_PROVIDER_MODEL=file-model\nANSWER_PROVIDER_API_KEY=synthetic-file-key\n"
        "ANSWER_PROVIDER_URL=https://example.test/v1\nANSWER_PROVIDER_NAME=File Provider\n"
    )
    monkeypatch.setenv(key_name, "synthetic-process-key")
    monkeypatch.setenv("ANSWER_PROVIDER_MODEL", "process-model")
    monkeypatch.setenv("ANSWER_PROVIDER_URL", config.GROQ_BASE_URL)
    monkeypatch.setenv("ANSWER_PROVIDER_NAME", "Groq")
    settings = config.get_settings()
    assert settings.answer_provider_api_key == "synthetic-process-key"
    assert settings.answer_provider_model == "process-model"
    assert settings.answer_provider_url == config.GROQ_BASE_URL
    assert settings.answer_provider_name == "Groq"


def test_primary_key_wins_with_fallback_for_empty_primary(env_file, monkeypatch):
    monkeypatch.setenv("ANSWER_PROVIDER_API_KEY", "synthetic-primary")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-fallback")
    assert config.get_settings().answer_provider_api_key == "synthetic-primary"
    monkeypatch.setenv("ANSWER_PROVIDER_API_KEY", "  ")
    assert config.get_settings().answer_provider_api_key == "synthetic-fallback"


def test_missing_model_is_not_invented_and_partial_configuration_can_start(env_file):
    env_file.write_text("GROQ_API_KEY=synthetic-key\n")
    assert config.get_settings().answer_provider_model == ""
    env_file.unlink()
    assert config.get_settings().answer_provider_api_key == ""


def test_model_keep_alive_is_configurable_with_process_precedence(env_file, monkeypatch):
    assert config.get_settings().ollama_keep_alive_seconds == 900
    env_file.write_text("OLLAMA_KEEP_ALIVE_SECONDS=300\n")
    assert config.get_settings().ollama_keep_alive_seconds == 300
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE_SECONDS", "600")
    assert config.get_settings().ollama_keep_alive_seconds == 600


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_invalid_model_keep_alive_is_rejected(env_file, monkeypatch, value):
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE_SECONDS", value)
    with pytest.raises(ValueError, match="OLLAMA_KEEP_ALIVE_SECONDS"):
        config.get_settings()


def test_aws_bind_requires_explicit_mode_and_proxy_secret(env_file, monkeypatch):
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    with pytest.raises(ValueError):
        config.get_settings()
    monkeypatch.setenv("DEPLOYMENT_MODE", "aws")
    with pytest.raises(ValueError):
        config.get_settings()
    monkeypatch.setenv("PRIVACYPAL_PROXY_TOKEN", "x" * 32)
    settings = config.get_settings()
    assert settings.host == "0.0.0.0" and settings.deployment_mode == "aws"
    assert "x" * 32 not in repr(settings)


@pytest.mark.parametrize("url", ["http://api.groq.com/openai/v1", "https://user:secret@example.test/v1", "https://example.test/v1?key=secret"])
def test_invalid_provider_url_fails_without_exposing_value(env_file, monkeypatch, url):
    monkeypatch.setenv("ANSWER_PROVIDER_URL", url)
    with pytest.raises(ValueError) as error:
        config.get_settings()
    assert url not in str(error.value)
    assert "secret" not in str(error.value)
