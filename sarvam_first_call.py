"""Optional manual connectivity check; sends one synthetic greeting to Sarvam."""
from backend.app.config import get_settings


def main() -> None:
    from sarvamai import SarvamAI

    settings = get_settings()
    if not settings.sarvam_api_key:
        raise SystemExit("Configure SARVAM_API_KEY in backend/.env or the backend environment.")
    client = SarvamAI(api_subscription_key=settings.sarvam_api_key)
    response = client.chat.completions(
        model=settings.sarvam_chat_model,
        messages=[{"role": "user", "content": "Reply with a short greeting."}],
    )
    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
