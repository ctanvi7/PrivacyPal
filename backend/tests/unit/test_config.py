from app.config import get_settings


def test_groq_api_key_selects_groq_openai_compatible_defaults(monkeypatch):
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
    assert settings.answer_provider_url == "https://api.groq.com/openai/v1/chat/completions"
    assert settings.answer_provider_model == "openai/gpt-oss-120b"
    assert settings.answer_provider_api_key == "synthetic-groq-test-key"
    assert "synthetic-groq-test-key" not in repr(settings)
