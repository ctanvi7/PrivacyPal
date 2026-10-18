#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export AWS_DEFAULT_REGION='${AWS::Region}'
export DEPLOY_BUCKET='${ArtifactBucket}'
export DEPLOY_KEY='${BackendArtifactKey}'
export RUNTIME_SECRET='${RuntimeSecret}'
export GEMMA_MODEL='${GemmaModel}'

systemctl stop privacypal 2>/dev/null || true
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip curl unzip tesseract-ocr
id privacypal >/dev/null 2>&1 || useradd --system --home /opt/privacypal --shell /usr/sbin/nologin privacypal
mkdir -p /opt/privacypal/current /etc/privacypal
python3 -m venv /opt/privacypal/venv
/opt/privacypal/venv/bin/pip install --quiet boto3
/opt/privacypal/venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
import shlex
import zipfile
import boto3

region = os.environ['AWS_DEFAULT_REGION']
boto3.client('s3', region_name=region).download_file(os.environ['DEPLOY_BUCKET'], os.environ['DEPLOY_KEY'], '/tmp/privacypal-source.zip')
with zipfile.ZipFile('/tmp/privacypal-source.zip') as bundle:
    bundle.extractall('/opt/privacypal/current')
Path('/tmp/privacypal-source.zip').unlink()
secret = json.loads(boto3.client('secretsmanager', region_name=region).get_secret_value(SecretId=os.environ['RUNTIME_SECRET'])['SecretString'])
values = {
    'DEPLOYMENT_MODE': 'aws', 'APP_HOST': '0.0.0.0', 'APP_PORT': '8000',
    'FRONTEND_ORIGIN': 'http://127.0.0.1:5173', 'OLLAMA_BASE_URL': 'http://127.0.0.1:11434',
    'GEMMA_MODEL': os.environ['GEMMA_MODEL'], 'MODEL_TIMEOUT_SECONDS': '180',
    'OLLAMA_KEEP_ALIVE_SECONDS': '900', 'PDF_MAX_BYTES': '4194304',
    'PRIVACYPAL_PROXY_TOKEN': secret['proxy_token'],
    'ANSWER_PROVIDER_NAME': secret['answer_provider_name'],
    'ANSWER_PROVIDER_URL': secret['answer_provider_url'],
    'ANSWER_PROVIDER_MODEL': secret['answer_provider_model'],
    'ANSWER_PROVIDER_API_KEY': secret['answer_provider_api_key'],
}
path = Path('/etc/privacypal/runtime.env')
path.write_text(''.join(key + '=' + shlex.quote(value) + '\n' for key, value in values.items()))
path.chmod(0o600)
PY
/opt/privacypal/venv/bin/pip install --quiet /opt/privacypal/current/backend
if ! command -v ollama >/dev/null; then
  curl -fsSL --retry 5 https://ollama.com/install.sh -o /tmp/privacypal-ollama-install.sh
  sh /tmp/privacypal-ollama-install.sh
  rm -f /tmp/privacypal-ollama-install.sh
fi
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/privacypal.conf <<'SERVICE'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_CONTEXT_LENGTH=8192"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_DEBUG=false"
SERVICE
systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama
for attempt in $(seq 1 60); do
  curl -fsS http://127.0.0.1:11434/api/version >/dev/null && break
  sleep 2
done
runuser -u ollama -- ollama pull "$GEMMA_MODEL"
cat > /etc/systemd/system/privacypal.service <<'SERVICE'
[Unit]
Description=PrivacyPal private processing backend
After=network-online.target ollama.service
Wants=network-online.target
Requires=ollama.service

[Service]
Type=simple
User=privacypal
Group=privacypal
WorkingDirectory=/opt/privacypal/current/backend
EnvironmentFile=/etc/privacypal/runtime.env
ExecStart=/opt/privacypal/venv/bin/python -u run.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
UMask=0077

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable --now privacypal
echo "$DEPLOY_KEY" > /opt/privacypal/deployment-source.txt
