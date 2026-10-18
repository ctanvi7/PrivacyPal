import os
from pathlib import Path

from sarvamai import SarvamAI


def load_key_from_env_file() -> None:
    env_file = Path(__file__).with_name(".env")
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() == "SARVAM_API_KEY":
            os.environ.setdefault("SARVAM_API_KEY", value.strip().strip("\"'"))
            return


load_key_from_env_file()
api_key = os.environ.get("SARVAM_API_KEY", "").strip()
if not api_key:
    raise SystemExit("SARVAM_API_KEY is missing. Add your key to the project .env file, then run this script again.")

client = SarvamAI(api_subscription_key=api_key)
response = client.chat.completions(
    model="sarvam-105b-conversations",
    messages=[{"role": "user", "content": "Reply with a short greeting."}],
)
print(response.choices[0].message.content)
