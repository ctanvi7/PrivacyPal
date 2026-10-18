# AWS CPU demo

This optional mode was authorized on 18 October 2026. It fully hosts document
processing and Gemma in AWS; it does not keep uploads on the user's PC.
Local mode remains the default. The deployment follows Ghostwork's Python 3.12
Lambda Web Adapter packaging pattern in `ap-south-1`.

## Architecture and privacy boundary

The HTTPS Lambda Function URL serves the React build and an authenticated proxy.
The browser sign-in page protects both UI and API using the existing demo
credentials and an eight-hour signed HttpOnly, Secure, SameSite=Strict access
cookie. Credentials and access cookies are not forwarded to the backend.
Basic authentication remains available for API clients; browser sign-in does
not depend on a WWW-Authenticate challenge, which Lambda remaps.
Login responses use `Referrer-Policy: same-origin`: a `no-referrer` policy
causes native browser form submissions to send a null Origin and fail the
strict Origin check. Other application responses retain `no-referrer`.
Null, absent, and foreign Origins remain rejected for state-changing requests.
See [the browser policy behavior](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy#effect_on_the_origin_header).
State-changing requests must carry the exact hosted Origin. The proxy forwards only approved headers,
sets a private token, and preserves the backend's HttpOnly, Secure,
SameSite=Strict ownership cookie. Provider credentials never reach the browser.

One `m6a.xlarge` CPU instance (4 vCPU, 16 GiB RAM) runs one FastAPI backend and
Ollama/Gemma. Lambda reaches port 8000 over the VPC. There is no public inbound
rule, SSH access, or exposed Ollama port. Ollama listens only on loopback.
The instance has an outbound public IPv4 address for installation, model
downloads, SSM, and the configured answer provider. The Lambda subnet has no
internet route or NAT gateway.

Uploads, extracted text, mappings, and workflow state live in the backend's
temporary memory. Lambda keeps no session state. Clearing or expiring the
session, restarting the backend, or replacing the instance discards that state.
There is no document bucket, database, permanent history, user account system,
or multi-user service guarantee. The private S3 bucket contains deployment
code only. The root disk is an encrypted 32-GiB gp3 volume.

Only the exact current sanitized draft may reach the answer provider, after
explicit approval. Tool permissions, edit invalidation, consumed approvals,
session ownership, secret blocking, and fail-closed checks remain enforced by
the backend. Detection can miss sensitive details. Logs must contain only
operational metadata, never uploaded content, prompts, answers, or credentials.

AWS uploads are limited to **4 MiB**, accounting for Lambda's buffered payload
and multipart/base64 overhead. Other extraction limits remain unchanged.
CPU inference can be slow, especially on the first request. This is a protected
single-host demo; production tenancy, availability, abuse controls, and durable
state need a separate design.
For CPU inference, each model call has a 180-second timeout and the final audit
has a 768-token generation budget. The gateway waits up to 570 seconds, while
Lambda and the hosted frontend allow 600 seconds, covering up to three model
calls plus orchestration. These limits do not skip checks or permit truncated
tool output. Logs distinguish `GenerationLimit`, incomplete output, and timeouts
without retaining prompts, source text, responses, or reasoning.
The backend admits one complete Gemma workflow at a time. Overlapping questions
receive `429 MODEL_BUSY` and can be retried after the active review finishes;
this prevents multiple sessions from filling the CPU model queue and timing out.
Edited-draft checks share the same model capacity and remain unapproved if busy.

## Deploy or update

From the repository root, with an authenticated AWS CLI and the local backend
provider configuration available:

The account must be on AWS's Paid account plan: the Free account plan blocks
the 16-GiB CPU instance, even when promotional credits remain. Upgrade through
the AWS Console before deploying. The script checks this before creating or
updating resources; it never changes the account plan itself.

```powershell
.\.venv\Scripts\python.exe scripts/deploy_aws.py --build-only
.\.venv\Scripts\python.exe scripts/deploy_aws.py --deploy
.\.venv\Scripts\python.exe scripts/deploy_aws.py --gateway-only
```

The deploy command builds Linux dependencies without Docker, validates the
CloudFormation template, uploads allowlisted application files, creates or
updates stack `privacypal`, and waits for EC2 installation and Gemma download.
It transfers only allowlisted provider settings into Secrets Manager; `.env`
files, local documents, backups, and development environments are excluded.
Updates preserve the login and proxy token. A gateway-only update changes only
the Lambda package and preserves processing sessions. A full deploy refreshes runtime
configuration and restarts the backend, discarding existing in-memory sessions.
Do not update during an approval send. Infrastructure changes can also restart
the CPU instance.

The protected URL and resource IDs are written to ignored
`deploy/aws/deployment.json`. Login details are saved outside OneDrive at
`$env:LOCALAPPDATA\PrivacyPal\aws-demo-access.json`. Keep that file private.
The runtime secret is also in Secrets Manager under `privacypal/runtime`.
Do not copy secrets into terminal output, issues, source control, or screenshots.

## Operate and stop costs

EC2 incurs compute charges while running; this CPU choice is not serverless.
EBS, public IPv4, Secrets Manager, S3, Lambda, logs, and data transfer can also
incur charges. Stopping the instance interrupts the app and loses its sessions;
the encrypted disk and other retained resources can still incur charges.

```powershell
$deployment = Get-Content deploy/aws/deployment.json | ConvertFrom-Json
aws ec2 stop-instances --instance-ids $deployment.InstanceId --region ap-south-1
aws ec2 start-instances --instance-ids $deployment.InstanceId --region ap-south-1
aws cloudformation describe-stacks --stack-name privacypal --region ap-south-1
```

SSM Run Command is the management channel. Check `systemctl is-active
privacypal ollama`, `/health` on port 8000 from the instance, and model presence
through the loopback Ollama API. Lambda `/health` checks only the gateway;
creating an authenticated session checks the actual backend. Do not print
`runtime.env`, Secrets Manager values, request/response bodies, or model output.

To permanently remove the deployment, first export only code/configuration you
need and then delete CloudFormation stack `privacypal`. This terminates EC2
and deletes its disk and application sessions. Delete the separate deployment
artifact bucket after checking its name against `deployment.json`; it is not
managed by the stack. Secrets Manager normally schedules secret deletion with
a recovery window. Remove the local login file when access is no longer needed.

## Validation

Normal tests use fake model/provider adapters. Hosted smoke checks must use
synthetic documents and stop at the privacy-review screen or cancel; they must
not approve a real provider call. Verify unauthenticated rejection, HTTPS cookie
flags, Origin rejection, upload, page selection, redaction, cancellation, and
session cleanup. Never use real sensitive documents as deployment fixtures.

Run `python scripts/smoke_aws.py` for protected UI/upload checks. Add `--review`
to run Gemma on the generated quick-test PDF; it cancels the workflow and clears
only its synthetic session without approving a provider send.
Use `python scripts/smoke_aws.py --review --question "explain this please"`
to verify the generic-question regression against the synthetic PDF.

Hosted verification on 18 October 2026 passed authentication, exact Origin
rejection, Secure/HttpOnly/SameSite ownership cookies, and the synthetic one-page
PDF upload. Gemma completed the review in 94.64 seconds, selected page 1, and
returned two findings. The test cancelled the review and cleared its session;
no provider send was approved. AWS checks confirmed an active Lambda gateway,
running `m6a.xlarge`, an encrypted root disk, blocked public S3 access, and API
ingress only from the gateway security group on port 8000. CPU timings vary with
model residency and load.

The exact question `explain this please` subsequently passed hosted review in
130.15 seconds with page 1 selected and two findings. A concurrent synthetic
question returned `429 MODEL_BUSY` in 0.13 seconds with all checks pending.
Both synthetic sessions were cleared and no provider send was approved.
The corresponding source passed 186 backend tests and 68 frontend tests.

Follow-up reliability verification: `explain the pdf` passed hosted review in
129.59 seconds, selecting page 1 and returning two findings. A fresh CPU model
load accounted for 51.7 seconds. Runtime inspection confirmed the 180-second
model timeout, 768-token audit budget, and active Lambda with a 600-second
timeout. Source validation passed 197 backend tests and 68 frontend tests.
No provider send was approved and the synthetic session was cleared.

Browser sign-in was subsequently changed to an HTML form because the Function
URL remaps `WWW-Authenticate` and prevents the native browser prompt. Hosted
verification passed the sign-in redirect, form submission, secure access
cookie, authenticated UI/assets, Origin guard, ownership cookie, and synthetic
PDF upload. The synthetic session was cleared. Twelve focused gateway tests
also passed, including invalid credentials, expired/forged cookies, and keeping
the gateway credential out of backend requests.

### Optional Sarvam services

Configure `SARVAM_API_KEY` securely in the backend runtime, with HTTPS egress to `api.sarvam.ai`; never place it in a frontend variable or deployment artifact. The backend loads `backend/.env` with process precedence. Restart the backend after configuration changes. The UI reports AWS processing and explicitly names Sarvam for each optional outbound translation/speech action.

Audio uploads share the existing 4 MiB gateway request limit. WAV speech responses have a separate bounded 5 MiB JSON allowance, below the synchronous Lambda response envelope; ordinary responses remain limited to 512 KiB. Longer responses fail safely without retry or another provider. No deployment has been performed as part of this conflict resolution.
