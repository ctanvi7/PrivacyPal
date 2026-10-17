"""Bounded deterministic detection, minimization, masking, and residual checks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

MAX_ANALYSIS_CHARS = 25_000
MAX_DRAFT_CHARS = 8_000
MAX_QUESTION_CHARS = 2_000
MAX_FINDINGS = 100
Action = Literal["mask", "omit", "block"]


class PrivacyCheckError(ValueError):
    """A mandatory privacy check could not safely complete."""


@dataclass(frozen=True)
class Finding:
    finding_id: str
    category: str
    action: Action
    reason: str
    start: int
    end: int
    _value: str = field(repr=False)

    def public_view(self) -> dict[str, str]:
        return {"finding_id": self.finding_id, "category": self.category, "action": self.action, "reason": self.reason}


@dataclass(frozen=True)
class ScanResult:
    findings: tuple[Finding, ...]
    complete: bool = True

    def public_view(self) -> dict[str, object]:
        return {"complete": self.complete, "findings": [item.public_view() for item in self.findings]}


@dataclass(frozen=True)
class SelectedContent:
    text: str
    source_sentence_count: int
    selected_sentence_count: int
    status: Literal["selected", "no_relevant_content"]


@dataclass(frozen=True)
class SanitizedDraft:
    text: str
    findings: tuple[Finding, ...]
    selection_status: Literal["selected", "no_relevant_content"]
    # This mapping is session-only and must never be serialized or logged.
    placeholder_map: dict[str, str] = field(repr=False)

    def public_view(self) -> dict[str, object]:
        return {"text": self.text, "findings": [item.public_view() for item in self.findings], "selection_status": self.selection_status}


@dataclass(frozen=True)
class ResidualReview:
    status: Literal["ready_for_user_review", "needs_review", "blocked"]
    findings: tuple[Finding, ...]
    reasons: tuple[str, ...]

    def public_view(self) -> dict[str, object]:
        return {"status": self.status, "findings": [item.public_view() for item in self.findings], "reasons": list(self.reasons)}


_PATTERNS: tuple[tuple[str, Action, str, re.Pattern[str]], ...] = (
    ("credential", "block", "A credential-like value must not be included in an outbound draft.",
     re.compile(r"(?i)\b(?:password|passwd|passcode|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|secret[_ -]?key)\b\s*[:=]\s*['\"]?([A-Za-z0-9_./+=-]{1,512})")),
    ("credential", "block", "A recognized private key or provider token must not be sent.",
     re.compile(r"(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|$))|\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("payment_card", "block", "A payment-card number is blocked from an outbound draft.",
     re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")),
    ("government_id", "mask", "A government-identifier pattern should be masked.",
     re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("email", "mask", "Email addresses can identify a person and are masked by default.",
     re.compile(r"(?i)\b[A-Z0-9.!#$%&'*+/=?^_{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+\b")),
    ("phone", "mask", "Phone-number patterns can identify a person and are masked by default.",
     re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{5,}\d)(?!\w)")),
    ("account_identifier", "mask", "A labeled account or identity number should be masked.",
     re.compile(r"(?i)\b(?:account|acct|member|customer|policy|claim|employee|student|patient)\s*(?:number|no\.?|id)\s*[:#=-]?\s*([A-Z0-9][A-Z0-9-]{3,})")),
)


def _luhn_valid(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def scan_sensitive_data(text: str) -> ScanResult:
    """Find common patterns; absence of findings is not a guarantee of safety."""
    if not isinstance(text, str) or len(text) > MAX_ANALYSIS_CHARS:
        raise PrivacyCheckError("Privacy scan input is invalid or exceeds the configured limit.")
    candidates = []
    priority = {"block": 0, "omit": 1, "mask": 2}
    for category, action, reason, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            has_value_group = category == "account_identifier" and match.lastindex and match.group(1) is not None
            start, end = match.span(1) if has_value_group else match.span()
            value = text[start:end]
            if category == "payment_card" and not _luhn_valid(value):
                continue
            candidates.append((priority[action], category, action, reason, start, end, value))
            if len(candidates) > MAX_FINDINGS:
                raise PrivacyCheckError("The privacy scan produced too many findings to review safely.")
    candidates.sort(key=lambda item: (item[0], -(item[5] - item[4]), item[4], item[1]))
    accepted = []
    occupied: list[tuple[int, int]] = []
    for _, category, action, reason, start, end, value in candidates:
        if any(start < right and left < end for left, right in occupied):
            continue
        accepted.append((category, action, reason, start, end, value))
        occupied.append((start, end))
    accepted.sort(key=lambda item: (item[3], item[4]))
    findings = tuple(
        Finding(f"finding-{category}-{start}-{end}", category, action, reason, start, end, value)
        for index, (category, action, reason, start, end, value) in enumerate(accepted, start=1)
    )
    return ScanResult(findings)


_WORD = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)
_STOP_WORDS = {"about", "after", "also", "and", "are", "can", "does", "for", "from", "how", "into", "its", "more", "need", "not", "that", "the", "their", "there", "these", "they", "this", "was", "what", "when", "where", "which", "who", "will", "with"}


def _terms(text: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(text) if word.casefold() not in _STOP_WORDS}


def select_relevant_content(question: str, source_text: str, *, max_chars: int = MAX_DRAFT_CHARS) -> SelectedContent:
    """Select matching sentences in source order; do not guess if none match."""
    if not isinstance(question, str) or not isinstance(source_text, str) or len(question) > MAX_QUESTION_CHARS or len(source_text) > MAX_ANALYSIS_CHARS:
        raise PrivacyCheckError("Question or source content is invalid or exceeds the configured limit.")
    if not 1 <= max_chars <= MAX_DRAFT_CHARS:
        raise PrivacyCheckError("Selected-content limit is invalid.")
    # Split after sentence punctuation only when followed by whitespace and a
    # plausible sentence start; this avoids cutting email addresses at dots.
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])|\n+", source_text)
        if sentence.strip()
    ]
    query_terms = _terms(question)
    scored = [(len(query_terms & _terms(sentence)), index, sentence) for index, sentence in enumerate(sentences)]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen: set[int] = set()
    used = 0
    for _, index, sentence in scored:
        addition = len(sentence) + bool(chosen)
        if used + addition <= max_chars:
            chosen.add(index)
            used += addition
    selected = " ".join(sentence for index, sentence in enumerate(sentences) if index in chosen)
    return SelectedContent(selected, len(sentences), len(chosen), "selected" if chosen else "no_relevant_content")


def _apply_actions(text: str, findings: tuple[Finding, ...], actions: dict[str, str]) -> tuple[str, dict[str, str]]:
    replacements = []
    mapping: dict[str, str] = {}
    placeholders: dict[tuple[str, str], str] = {}
    for finding in findings:
        requested = actions.get(finding.finding_id)
        if requested not in {None, "mask", "omit", "keep"}:
            raise PrivacyCheckError("A proposed finding action is not supported.")
        action = "omit" if finding.action == "block" else (requested or "mask")
        if action == "keep":
            continue
        if action == "omit":
            replacement = ""
        else:
            key = (finding.category, finding._value.casefold())
            if key not in placeholders:
                placeholder = f"[{finding.category.upper()}_{len(placeholders) + 1}]"
                placeholders[key] = placeholder
                mapping[placeholder] = finding._value
            replacement = placeholders[key]
        replacements.append((finding.start, finding.end, replacement))
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text, mapping


def build_sanitized_draft(question: str, source_text: str, *, actions: dict[str, str] | None = None, max_chars: int = MAX_DRAFT_CHARS) -> SanitizedDraft:
    """Build a minimized draft; block/omit known secrets regardless of model advice."""
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CHARS:
        raise PrivacyCheckError("A valid question is required to build a draft.")
    if actions is not None and not isinstance(actions, dict):
        raise PrivacyCheckError("Proposed finding actions are malformed.")
    prefix = f"Question: {question.strip()}\n\nRelevant context:\n"
    context_limit = max_chars - len(prefix)
    if context_limit < 1:
        raise PrivacyCheckError("The draft limit is too small for this question.")
    selected = select_relevant_content(question, source_text, max_chars=context_limit)
    # Select only whole sentences that fit. Never slice through a sensitive value.
    draft = prefix + selected.text
    scan = scan_sensitive_data(draft)
    unknown_actions = set(actions or {}) - {item.finding_id for item in scan.findings}
    if unknown_actions:
        raise PrivacyCheckError("A proposed action refers to an unknown finding.")
    sanitized, mapping = _apply_actions(draft, scan.findings, actions or {})
    residual = scan_sensitive_data(sanitized)
    if any(item.action == "block" for item in residual.findings):
        raise PrivacyCheckError("A high-risk value remains after sanitization.")
    return SanitizedDraft(sanitized, scan.findings, selected.status, mapping)


_CONTEXT_FLAG_REASONS = {
    "email": "Contextual review flagged a possible email clue.",
    "phone": "Contextual review flagged a possible phone clue.",
    "location": "Contextual review flagged a possible location clue.",
    "unique_fact": "Contextual review flagged a potentially unique fact.",
    "combination": "Contextual review flagged a combination of identifying details.",
    "other": "Contextual review flagged another possible identity clue.",
}


def review_residual_risk(draft: str, *, contextual_flags: tuple[str, ...] = (), contextual_review_complete: bool = False) -> ResidualReview:
    """Review the exact draft and fail closed when contextual review did not finish."""
    if not isinstance(draft, str) or len(draft) > MAX_DRAFT_CHARS:
        raise PrivacyCheckError("Residual-review input is invalid or too large.")
    if not isinstance(contextual_flags, tuple) or any(
        not isinstance(flag, str) or flag not in _CONTEXT_FLAG_REASONS for flag in contextual_flags
    ):
        raise PrivacyCheckError("Residual-review flags are malformed.")
    scan = scan_sensitive_data(draft)
    reasons: list[str] = []
    if any(item.action == "block" for item in scan.findings):
        status = "blocked"
        reasons.append("A high-risk pattern remains in the exact draft.")
    elif not contextual_review_complete:
        status = "needs_review"
        reasons.append("Contextual residual-risk review did not complete.")
    elif contextual_flags or scan.findings:
        status = "needs_review"
        reasons.extend(_CONTEXT_FLAG_REASONS[flag] for flag in contextual_flags)
        if scan.findings:
            reasons.append("Known identifier patterns remain in the exact draft.")
    else:
        status = "ready_for_user_review"
        reasons.append("No configured high-risk patterns were detected; user review is still required.")
    return ResidualReview(status, scan.findings, tuple(reasons))
