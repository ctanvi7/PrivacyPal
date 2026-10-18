"""Build or deploy the protected CPU demo in ap-south-1.

    .venv/Scripts/python.exe scripts/deploy_aws.py --build-only
    .venv/Scripts/python.exe scripts/deploy_aws.py --deploy

Uses Ghostwork's Lambda Web Adapter pattern. Credentials are allowlisted into
Secrets Manager; .env files, documents, backups, and local venvs are not uploaded.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "aws"))
sys.path.insert(0, str(ROOT / "backend"))
from infrastructure import build_template
from app.config import get_settings

REGION = "ap-south-1"
STACK = "privacypal"
BUILD_ROOT = Path(tempfile.mkdtemp(prefix="privacypal-aws-"))


def aws(*arguments, missing=False):
    upload = arguments[:2] == ("s3api", "put-object")
    result = subprocess.run([
        "aws", *arguments, "--region", REGION, "--output", "json", "--no-cli-pager",
        "--cli-connect-timeout", "5", "--cli-read-timeout", "45" if upload else "15",
    ], capture_output=True, text=True, encoding="utf-8", timeout=120 if upload else 60,
        env={**os.environ, "AWS_MAX_ATTEMPTS": "2", "AWS_CLI_OUTPUT_ENCODING": "utf-8"})
    if result.returncode:
        if missing and any(value in result.stderr for value in ("does not exist", "NoSuchBucket", "Not Found", "(404)", "InvocationDoesNotExist")):
            return None
        if "No updates are to be performed" in result.stderr and arguments[:2] == ("cloudformation", "update-stack"):
            return {}
        raise RuntimeError(f"AWS {' '.join(arguments[:2])} failed; credentials/permissions or resource state need attention.")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def parameter_call(arguments, parameters):
    path = BUILD_ROOT / "private-parameters.json"
    path.write_text(json.dumps(parameters), encoding="utf-8")
    path.chmod(0o600)
    try:
        return aws(*arguments, "--parameters", f"file://{path}")
    finally:
        path.unlink(missing_ok=True)


def zip_tree(folder, destination):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                bundle.write(path, path.relative_to(folder).as_posix())
        script = zipfile.ZipInfo("run.sh")
        script.create_system = 3
        script.external_attr = 0o100755 << 16
        bundle.writestr(script, (ROOT / "deploy/aws/run.sh").read_text().replace("\r\n", "\n"))


def build():
    print("Building the AWS frontend and Linux Lambda package...", flush=True)
    env = {**os.environ, "VITE_DEPLOYMENT_MODE": "aws", "VITE_PRIVACYPAL_API_BASE_URL": ""}
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    result = subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Frontend production build failed.")
    package = BUILD_ROOT / "gateway"
    package.mkdir()
    result = subprocess.run([
        sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-compile",
        "-r", str(ROOT / "deploy/aws/gateway-requirements.txt"), "--target", str(package),
        "--platform", "manylinux2014_x86_64", "--implementation", "cp", "--python-version", "3.12",
        "--abi", "cp312", "--only-binary=:all:",
    ], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Linux Python dependency build failed.")
    (package / "app").mkdir(exist_ok=True)
    (package / "app/__init__.py").write_text('"""PrivacyPal AWS gateway."""\n')
    shutil.copy2(ROOT / "backend/app/cloud_gateway.py", package / "app/cloud_gateway.py")
    shutil.copytree(ROOT / "frontend/dist", package / "static")
    gateway = BUILD_ROOT / "gateway.zip"
    zip_tree(package, gateway)
    backend = BUILD_ROOT / "backend.zip"
    with zipfile.ZipFile(backend, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted((ROOT / "backend/app").rglob("*.py")):
            if "__pycache__" not in path.parts:
                bundle.write(path, path.relative_to(ROOT).as_posix())
        for name in ("backend/pyproject.toml", "backend/run.py"):
            bundle.write(ROOT / name, name)
    template = BUILD_ROOT / "template.json"
    template.write_text(json.dumps(build_template((ROOT / "deploy/aws/bootstrap.sh").read_text()), indent=2))
    for artifact in (gateway, backend):
        with zipfile.ZipFile(artifact) as bundle:
            assert bundle.testzip() is None
            assert not any(Path(name).name == ".env" or "backups/" in name for name in bundle.namelist())
    print(json.dumps({"build_directory": str(BUILD_ROOT), "gateway_bytes": gateway.stat().st_size, "backend_bytes": backend.stat().st_size}), flush=True)
    return gateway, backend, template


def stack_outputs(stack):
    return {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}


def wait_stack():
    last = None
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        stack = aws("cloudformation", "describe-stacks", "--stack-name", STACK)["Stacks"][0]
        status = stack["StackStatus"]
        if status != last:
            print(f"CloudFormation: {status}", flush=True)
            last = status
        if status in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
            return stack
        if "FAILED" in status or "ROLLBACK" in status:
            raise RuntimeError("Stack deployment failed; inspect the CloudFormation events.")
        time.sleep(10)
    raise RuntimeError("Stack is still provisioning; check CloudFormation before retrying.")


def ensure_bucket(bucket):
    existing = aws("s3api", "head-bucket", "--bucket", bucket, missing=True)
    if existing is None:
        aws("s3api", "create-bucket", "--bucket", bucket, "--create-bucket-configuration", f"LocationConstraint={REGION}")
    aws("s3api", "put-public-access-block", "--bucket", bucket, "--public-access-block-configuration",
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true")
    encryption = BUILD_ROOT / "encryption.json"
    encryption.write_text(json.dumps({"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}))
    aws("s3api", "put-bucket-encryption", "--bucket", bucket, "--server-side-encryption-configuration", f"file://{encryption}")


def upload_artifact(bucket, key, artifact):
    checksum = base64.b64encode(hashlib.sha256(artifact.read_bytes()).digest()).decode()
    existing = aws("s3api", "head-object", "--bucket", bucket, "--key", key, "--checksum-mode", "ENABLED", missing=True)
    if existing and existing.get("ChecksumSHA256") == checksum and existing["ContentLength"] == artifact.stat().st_size:
        return
    result = aws("s3api", "put-object", "--bucket", bucket, "--key", key, "--body", str(artifact),
        "--server-side-encryption", "AES256", "--checksum-algorithm", "SHA256", "--checksum-sha256", checksum)
    if result.get("ChecksumSHA256") != checksum:
        raise RuntimeError("Uploaded artifact integrity could not be verified.")


def deploy(gateway, backend, template):
    identity = aws("sts", "get-caller-identity")
    account = identity["Account"]
    plan = aws("freetier", "get-account-plan-state")
    if plan.get("accountPlanType") == "FREE":
        raise RuntimeError("AWS Free account plan blocks the 16-GiB CPU instance. Upgrade the account plan in the AWS Console before deployment; no resources were changed by this run.")
    settings = get_settings()
    existing_result = aws("cloudformation", "describe-stacks", "--stack-name", STACK, missing=True)
    existing = existing_result["Stacks"][0] if existing_result else None
    if existing and existing["StackStatus"] == "ROLLBACK_COMPLETE":
        raise RuntimeError("The previous create attempt rolled back. Delete the failed privacypal stack before retrying; its application resources are already removed.")
    outputs = stack_outputs(existing) if existing else {}
    if existing:
        stored = aws("secretsmanager", "get-secret-value", "--secret-id", outputs["RuntimeSecretArn"])
        runtime = json.loads(stored["SecretString"])
    else:
        runtime = {"demo_username": "privacypal", "demo_password": secrets.token_urlsafe(32), "proxy_token": secrets.token_urlsafe(32)}
    runtime.update({
        "answer_provider_name": settings.answer_provider_name, "answer_provider_url": settings.answer_provider_url,
        "answer_provider_model": settings.answer_provider_model, "answer_provider_api_key": settings.answer_provider_api_key,
    })
    previous_parameters = {item["ParameterKey"]: item.get("ParameterValue") for item in existing.get("Parameters", [])} if existing else {}
    ami = previous_parameters.get("AmiId") or aws("ssm", "get-parameter", "--name", "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id")["Parameter"]["Value"]
    offerings = aws("ec2", "describe-instance-type-offerings", "--location-type", "availability-zone", "--filters", "Name=instance-type,Values=m6a.xlarge")["InstanceTypeOfferings"]
    zone = previous_parameters.get("AvailabilityZone") or sorted(item["Location"] for item in offerings)[0]
    aws("cloudformation", "validate-template", "--template-body", f"file://{template}")
    bucket = f"privacypal-artifacts-{account}-{REGION}"
    ensure_bucket(bucket)
    backend_key = f"releases/{hashlib.sha256(backend.read_bytes()).hexdigest()}/backend.zip"
    gateway_key = f"releases/{hashlib.sha256(gateway.read_bytes()).hexdigest()}/gateway.zip"
    for artifact, key in ((backend, backend_key), (gateway, gateway_key)):
        upload_artifact(bucket, key, artifact)
    values = {
        "ArtifactBucket": bucket, "BackendArtifactKey": backend_key, "GatewayArtifactKey": gateway_key,
        "RuntimeSecretJson": json.dumps(runtime), "PublicOrigin": outputs.get("Url", "https://not-ready.invalid").rstrip("/"),
        "AmiId": ami, "AvailabilityZone": zone, "InstanceType": "m6a.xlarge", "GemmaModel": settings.gemma_model,
    }
    action = "update-stack" if existing else "create-stack"
    arguments = ["cloudformation", action, "--stack-name", STACK, "--template-body", f"file://{template}", "--capabilities", "CAPABILITY_IAM"]
    print(f"Deploying {STACK} in {REGION}: CPU m6a.xlarge, Lambda gateway, private API, encrypted 32-GiB disk.", flush=True)
    parameter_call(arguments, [{"ParameterKey": key, "ParameterValue": value} for key, value in values.items()])
    stack = wait_stack()
    outputs = stack_outputs(stack)
    origin = outputs["Url"].rstrip("/")
    if values["PublicOrigin"] != origin:
        parameters = [{"ParameterKey": key, "UsePreviousValue": True} for key in values if key != "PublicOrigin"]
        parameters.append({"ParameterKey": "PublicOrigin", "ParameterValue": origin})
        parameter_call(["cloudformation", "update-stack", "--stack-name", STACK, "--use-previous-template", "--capabilities", "CAPABILITY_IAM"], parameters)
        outputs = stack_outputs(wait_stack())
    private_folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PrivacyPal"
    private_folder.mkdir(exist_ok=True)
    access = private_folder / "aws-demo-access.json"
    access.write_text(json.dumps({"url": outputs["Url"], "username": runtime["demo_username"], "password": runtime["demo_password"]}, indent=2))
    access.chmod(0o600)
    metadata = {**outputs, "Region": REGION, "Stack": STACK, "ArtifactBucket": bucket}
    (ROOT / "deploy/aws/deployment.json").write_text(json.dumps(metadata, indent=2))
    print(json.dumps({"url": outputs["Url"], "instance_id": outputs["InstanceId"], "private_login_file": str(access)}), flush=True)
    print("Infrastructure is provisioned. EC2 bootstrap/model download may still be running; verify processing readiness before using the demo.", flush=True)
    wait_backend(outputs["InstanceId"], backend_key, bucket, outputs["RuntimeSecretArn"], settings.gemma_model)


def deploy_gateway(gateway):
    """Update only Lambda code, retaining backend sessions and configuration."""
    stack = aws("cloudformation", "describe-stacks", "--stack-name", STACK)["Stacks"][0]
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise RuntimeError("Gateway-only update requires an existing stable deployment.")
    values = {item["ParameterKey"]: item.get("ParameterValue") for item in stack["Parameters"]}
    key = f"releases/{hashlib.sha256(gateway.read_bytes()).hexdigest()}/gateway.zip"
    upload_artifact(values["ArtifactBucket"], key, gateway)
    parameters = [{"ParameterKey": name, "UsePreviousValue": True} for name in values if name != "GatewayArtifactKey"]
    parameters.append({"ParameterKey": "GatewayArtifactKey", "ParameterValue": key})
    print("Updating the Lambda gateway...", flush=True)
    parameter_call(["cloudformation", "update-stack", "--stack-name", STACK, "--use-previous-template", "--capabilities", "CAPABILITY_IAM"], parameters)
    outputs = stack_outputs(wait_stack())
    print(json.dumps({"gateway_updated": True, "url": outputs["Url"]}), flush=True)


def wait_backend(instance_id, backend_key, bucket, secret_arn, model):
    print("Waiting for SSM, backend installation, and Gemma download...", flush=True)
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        nodes = aws("ssm", "describe-instance-information", "--filters", f"Key=InstanceIds,Values={instance_id}").get("InstanceInformationList", [])
        if nodes and nodes[0].get("PingStatus") == "Online":
            break
        time.sleep(10)
    else:
        raise RuntimeError("Compute instance is not managed/online in SSM yet.")
    script = (ROOT / "deploy/aws/bootstrap.sh").read_text()
    for key, value in {"AWS::Region": REGION, "ArtifactBucket": bucket, "BackendArtifactKey": backend_key, "RuntimeSecret": secret_arn, "GemmaModel": model}.items():
        script = script.replace("${" + key + "}", value)
    commands = ["set -e", "cloud-init status --wait >/dev/null 2>&1 || true",
        f"bash <<'PRIVACYPAL_BOOTSTRAP'\n{script}\nPRIVACYPAL_BOOTSTRAP",
        "for attempt in $(seq 1 120); do curl -fsS http://127.0.0.1:8000/health >/dev/null && exit 0; sleep 5; done; exit 1"]
    command_file = BUILD_ROOT / "ssm-readiness.json"
    command_file.write_text(json.dumps({"commands": commands, "executionTimeout": ["1800"]}))
    command = aws("ssm", "send-command", "--instance-ids", instance_id, "--document-name", "AWS-RunShellScript",
        "--timeout-seconds", "1800", "--parameters", f"file://{command_file}")["Command"]["CommandId"]
    deadline = time.monotonic() + 2100
    last_update = 0
    while time.monotonic() < deadline:
        invocation = aws("ssm", "get-command-invocation", "--command-id", command, "--instance-id", instance_id, missing=True)
        if invocation is None:
            time.sleep(5)
            continue
        status = invocation["Status"]
        if time.monotonic() - last_update >= 30:
            print(f"Compute readiness: {status}", flush=True)
            last_update = time.monotonic()
        if status == "Success":
            print("Backend and Gemma are ready. Verify the protected public URL with the saved login.", flush=True)
            return
        if status in {"Failed", "Cancelled", "TimedOut", "Cancelling"}:
            raise RuntimeError(f"Compute readiness failed ({status}); inspect SSM command {command}.")
        time.sleep(10)
    raise RuntimeError("Compute setup is still running; inspect SSM before retrying.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build-only", action="store_true")
    mode.add_argument("--deploy", action="store_true")
    mode.add_argument("--gateway-only", action="store_true", help="Update the gateway without restarting the processing backend")
    args = parser.parse_args()
    artifacts = build()
    if args.deploy:
        deploy(*artifacts)
    elif args.gateway_only:
        deploy_gateway(artifacts[0])
