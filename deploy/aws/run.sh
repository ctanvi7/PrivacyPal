#!/bin/bash
set -euo pipefail
export PYTHONPATH="/var/task:${PYTHONPATH:-}"
exec python3 -m uvicorn app.cloud_gateway:create_app --factory --host 127.0.0.1 --port "${PORT:-8080}" --no-access-log
