"""Validate Gemma's proposed local redactions against the bound source text."""

import re

from app.privacy.pipeline import Finding, PrivacyCheckError

SEMANTIC_CATEGORIES = {
    "person_name", "email", "phone", "street_address", "lease_reference",
    "account_identifier", "government_id", "credential", "other_identity",
}
MAX_SEMANTIC_FINDINGS = 32


def validate_candidates(candidates: object) -> list[dict[str, str]]:
    if not isinstance(candidates, list) or len(candidates) > MAX_SEMANTIC_FINDINGS:
        raise PrivacyCheckError("Local identity detections are malformed or excessive.")
    for item in candidates:
        if (not isinstance(item, dict) or set(item) != {"category", "value"}
            or not isinstance(item["category"], str) or item["category"] not in SEMANTIC_CATEGORIES
            or not isinstance(item["value"], str) or not 2 <= len(item["value"].strip()) <= 500
            or re.fullmatch(r"\[[A-Z][A-Z0-9_]*\]", item["value"].strip())):
            raise PrivacyCheckError("A local identity detection is invalid.")
    return candidates


def validated_findings(source: str, candidates: object) -> tuple[Finding, ...]:
    findings = []
    for item in validate_candidates(candidates):
        pattern = re.compile(r"\s+".join(re.escape(part) for part in item["value"].split()))
        matches = list(pattern.finditer(source))
        if not matches:
            raise PrivacyCheckError("A model-proposed value could not be verified against the local source.")
        for match in matches:
            category = item["category"]
            findings.append(Finding(f"semantic-{category}-{match.start()}-{match.end()}", category,
                "block" if category == "credential" else "mask",
                "Gemma identified this source value for local redaction; the backend verified its location.",
                match.start(), match.end(), match.group()))
            if len(findings) > 100:
                raise PrivacyCheckError("Too many source spans were identified to review safely.")
    return tuple(findings)
