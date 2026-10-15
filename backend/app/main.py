"""FastAPI application entry point for PrivacyPal."""

from fastapi import FastAPI

app = FastAPI(title="PrivacyPal API", version="0.1.0")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Report that the HTTP application is running."""

    return {"status": "ok"}
