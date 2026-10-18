"""Start the local API using the validated loopback configuration."""

from copy import deepcopy

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    log_config = deepcopy(LOGGING_CONFIG)
    log_config["loggers"]["app.model.ollama_adapter"] = {
        "handlers": ["default"], "level": "INFO", "propagate": False,
    }
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_config=log_config)


if __name__ == "__main__":
    main()
