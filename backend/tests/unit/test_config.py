import app.config as config
from app.config import get_settings


def test_groq_api_key_uses_explicit_model_and_safe_provider_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BACKEND_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-groq-test-key")
    for name in (
        "ANSWER_PROVIDER_NAME",
        "ANSWER_PROVIDER_URL",
        "ANSWER_PROVIDER_MODEL",
        "ANSWER_PROVIDER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.answer_provider_name == "Groq"
    assert settings.answer_provider_url == "https://api.groq.com/openai/v1"
    assert settings.answer_provider_model == ""  # Model selection is explicit in PR #13.
    assert settings.answer_provider_api_key == "synthetic-groq-test-key"
    assert "synthetic-groq-test-key" not in repr(settings)
