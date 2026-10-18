"""Opt-in hosted smoke check with synthetic data; never approves a provider send."""

import argparse
import json
import os
from pathlib import Path
import re
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


def require(response, expected, stage):
    if response.status_code != expected:
        code = None
        try:
            code = response.json().get("error", {}).get("code")
        except (ValueError, AttributeError):
            pass
        raise RuntimeError(f"{stage}: HTTP {response.status_code}, code={code}; response content withheld")
    return response


def main(review, question="Explain the attached document."):
    access_path = Path(os.environ["LOCALAPPDATA"]) / "PrivacyPal/aws-demo-access.json"
    access = json.loads(access_path.read_text())
    origin = access["url"].rstrip("/")
    with httpx.Client(base_url=origin, timeout=450) as anonymous:
        require(anonymous.get("/health"), 200, "Gateway health")
        redirect = require(anonymous.get("/"), 303, "Sign-in redirect")
        if redirect.headers.get("location") != "/login":
            raise RuntimeError("Sign-in redirect is missing")
        sign_in = require(anonymous.get("/login"), 200, "Browser sign-in page")
        if 'name="password"' not in sign_in.text or 'action="/login"' not in sign_in.text:
            raise RuntimeError("Browser sign-in form is missing")
        if sign_in.headers.get("referrer-policy") != "same-origin":
            raise RuntimeError("Sign-in policy would suppress the browser form Origin")
        for untrusted_origin in ("null", "https://example.invalid"):
            require(anonymous.post("/login", headers={"Origin": untrusted_origin},
                data={"username": "synthetic", "password": "wrong"}), 403, "Untrusted login Origin rejection")
        require(anonymous.get("/api/v1/sessions/synthetic"), 401, "Anonymous API rejection")
    with httpx.Client(base_url=origin, timeout=620) as client:
        signed_in = require(client.post("/login", headers={"Origin": origin},
            data={"username": access["username"], "password": access["password"]}), 303, "Form sign-in")
        access_cookie = signed_in.headers.get("set-cookie", "").lower()
        if not all(flag in access_cookie for flag in ("__host-privacypal_access=", "secure", "httponly", "samesite=strict")):
            raise RuntimeError("Secure gateway access cookie is missing")
        html = require(client.get("/"), 200, "Authenticated UI").text
        script = re.search(r'src="([^"]+\.js)"', html)
        if not script:
            raise RuntimeError("Built UI script is missing")
        asset = require(client.get(script.group(1)), 200, "UI asset").text
        if "Documents are processed in AWS" not in asset:
            raise RuntimeError("AWS processing disclosure is missing")
        require(client.post("/api/v1/sessions", headers={"Origin": "https://example.invalid"}), 403, "Origin rejection")
        created = require(client.post("/api/v1/sessions", headers={"Origin": origin}), 201, "Session creation")
        cookie = created.headers.get("set-cookie", "").lower()
        if not all(value in cookie for value in ("httponly", "secure", "samesite=strict")):
            raise RuntimeError("Secure ownership cookie is missing")
        session = created.json()["session_id"]
        headers = {"Origin": origin}
        try:
            with (ROOT / "output/pdf/PrivacyPal_Quick_Test.pdf").open("rb") as document:
                uploaded = require(client.post(f"/api/v1/sessions/{session}/documents", headers=headers,
                    files={"file": ("PrivacyPal_Quick_Test.pdf", document, "application/pdf")}), 201, "Synthetic PDF upload").json()
            print(json.dumps({"gateway": "ready", "authentication": "passed", "origin_guard": "passed",
                "cookie": "secure", "synthetic_pdf_pages": uploaded["page_count"]}), flush=True)
            if review:
                started = time.monotonic()
                response = client.post(f"/api/v1/sessions/{session}/questions", headers=headers,
                    json={"document_id": uploaded["document_id"], "question": question})
                result = require(response, 200, "Gemma privacy review").json()
                if result.get("send_state") != "review" or not result.get("review_complete"):
                    raise RuntimeError("Privacy review is incomplete; nothing was approved")
                if result.get("pages_used") != [1] or not result.get("draft", "").strip():
                    raise RuntimeError("Sanitized source context is missing")
                # The synthetic fixture's email must not survive minimization.
                from pypdf import PdfReader
                fixture = "\n".join(page.extract_text() for page in PdfReader(ROOT / "output/pdf/PrivacyPal_Quick_Test.pdf").pages)
                emails = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", fixture)
                if any(email.casefold() in result["draft"].casefold() for email in emails):
                    raise RuntimeError("Synthetic email survived minimization")
                print(json.dumps({"gemma_review": "passed", "seconds": round(time.monotonic() - started, 2),
                    "pages_used": result["pages_used"], "findings": len(result.get("findings", [])),
                    "provider_send": "not approved"}), flush=True)
                require(client.post(f"/api/v1/sessions/{session}/workflows/{result['workflow_id']}/cancel", headers=headers), 200, "Cancellation")
        finally:
            require(client.post(f"/api/v1/sessions/{session}/clear", headers=headers), 200, "Synthetic session cleanup")
    print("Hosted smoke check passed; synthetic session cleared.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", action="store_true", help="Also run Gemma against the synthetic PDF, without approving a send")
    parser.add_argument("--question", default="Explain the attached document.", help="Synthetic review question; never use sensitive data")
    args = parser.parse_args()
    main(args.review, args.question)
