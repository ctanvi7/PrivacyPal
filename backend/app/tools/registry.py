"""Strict definitions and validation for Gemma's narrow native tool calls."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from app.privacy.grounding import review_outbound_identity
from app.privacy.semantic import SEMANTIC_CATEGORIES, MAX_SEMANTIC_FINDINGS, validate_candidates, validated_findings

from app.privacy.pipeline import (
    MAX_ANALYSIS_CHARS,
    MAX_DRAFT_CHARS,
    Finding,
    PrivacyCheckError,
    ResidualReview,
    SanitizedDraft,
    ScanResult,
    SelectedContent,
    build_sanitized_draft,
    review_residual_risk,
    scan_sensitive_data,
    select_relevant_content,
    redact_remaining_values,
)

MAX_TOOL_ARGUMENTS = 2_000
MAX_TOOL_CALLS = 5
_TOOL_ORDER = (
    "inspect_document",
    "detect_sensitive_data",
    "select_relevant_content",
    "propose_sanitized_request",
    "review_residual_risk",
)
_RISK_CATEGORIES = {"email", "phone", "location", "unique_fact", "combination", "other"}


class ToolValidationError(ValueError):
    """A model-proposed native tool call is not allowed or well-formed."""


@dataclass(frozen=True)
class ValidatedToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolContext:
    """Per-workflow state; the model never supplies session or document IDs."""

    session_id: str
    workflow_id: str
    question: str
    document_pages: tuple[dict[str, object], ...]
    inspected_pages: tuple[int, ...] = ()
    selected_pages: tuple[int, ...] = ()
    scan: ScanResult | None = None
    selected: SelectedContent | None = None
    draft: SanitizedDraft | None = None
    residual_review: ResidualReview | None = None
    contextual_flags: tuple[str, ...] = ()
    semantic_findings: tuple[Finding, ...] = field(default=(), repr=False)
    semantic_detection_complete: bool = False
    residual_recheck_required: bool = False
    executed_tools: list[str] = field(default_factory=list)
    search_terms: tuple[str, ...] = field(default=(), repr=False)

    @property
    def source_text(self) -> str:
        parts = []
        for item in self.document_pages:
            value = item.get("text")
            if not isinstance(value, str):
                raise ToolValidationError("The active workflow document is invalid.")
            parts.append(value)
        text = "\n\n".join(parts)
        if len(text) > MAX_ANALYSIS_CHARS:
            raise ToolValidationError("The active workflow document exceeds the analysis limit.")
        return text


class ToolRegistry:
    """Execute one allowlisted call at a time against a bound local workflow."""

    def prepare_draft(self, context: ToolContext) -> None:
        """Run deterministic preparation after validated native detection.

        These steps take no model arguments. Running them here avoids two model
        round trips without fabricating native calls or skipping privacy checks.
        """
        if context.executed_tools != list(_TOOL_ORDER[:2]) or context.scan is None or not context.scan.complete:
            raise ToolValidationError("Completed inspection and detection are required before preparation.")
        for name in _TOOL_ORDER[2:4]:
            try:
                self._run(ValidatedToolCall(name, {}), context)
            except PrivacyCheckError as exc:
                raise ToolValidationError("Local draft preparation could not complete.") from exc
            context.executed_tools.append(name)

    def execute(self, raw_call: object, context: ToolContext) -> dict[str, object]:
        call = validate_tool_call(raw_call)
        if call.name == "detect_sensitive_data" and "terms" in call.arguments:
            # One native call explicitly requests inspection and detection.
            # Reuse the same bound operations; never invent model detections.
            if context.executed_tools:
                raise ToolValidationError("Combined inspection and detection must start the workflow.")
            self._run(ValidatedToolCall("inspect_document", {"terms": call.arguments["terms"]}), context)
            context.executed_tools.append("inspect_document")
        if len(context.executed_tools) >= MAX_TOOL_CALLS or call.name in context.executed_tools:
            raise ToolValidationError("The workflow tool-call limit was reached.")
        if context.executed_tools and _TOOL_ORDER.index(call.name) <= _TOOL_ORDER.index(context.executed_tools[-1]):
            raise ToolValidationError("The requested tool is out of workflow order.")

        try:
            result = self._run(call, context)
        except PrivacyCheckError as exc:
            # Do not expose source values or model arguments in a safe error.
            raise ToolValidationError("A required local privacy check could not complete.") from exc
        context.executed_tools.append(call.name)
        return result

    def _run(self, call: ValidatedToolCall, context: ToolContext) -> dict[str, object]:
        if call.name == "inspect_document":
            terms = [term.casefold() for term in call.arguments["terms"]]
            context.search_terms = tuple(terms)
            passages = []
            pages_used = set()
            remaining = 8_000
            for page in context.document_pages:
                text = page.get("text")
                number = page.get("page")
                if not isinstance(text, str) or not isinstance(number, int):
                    raise ToolValidationError("The active workflow document is invalid.")
                lowered = text.casefold()
                for term in terms:
                    offset = lowered.find(term)
                    if offset >= 0:
                        passage = text[max(0, offset - 220):offset + len(term) + 320][:remaining]
                        if passage:
                            passages.append({"page": number, "text": passage})
                            pages_used.add(number)
                            remaining -= len(passage)
                        break
                if remaining <= 0:
                    break
            context.inspected_pages = tuple(sorted(pages_used))
            return {"passages": passages, "pages": list(context.inspected_pages)}

        if call.name == "detect_sensitive_data":
            context.semantic_detection_complete = "sensitive_spans" in call.arguments
            context.semantic_findings = validated_findings(context.source_text, call.arguments.get("sensitive_spans", []))
            context.scan = scan_sensitive_data(context.source_text, additional_findings=context.semantic_findings)
            return context.scan.public_view()

        if call.name == "select_relevant_content":
            context.selected = select_relevant_content(context.question, context.source_text, search_terms=context.search_terms)
            return {
                "content": context.selected.text,
                "status": context.selected.status,
                "selected_sentence_count": context.selected.selected_sentence_count,
            }

        if call.name == "propose_sanitized_request":
            if context.scan is None or context.selected is None:
                raise ToolValidationError("Detection and relevance selection must run before sanitization.")
            if context.selected.status != "selected":
                raise ToolValidationError("No relevant document content was found; the workflow needs review.")
            context.draft = build_sanitized_draft(context.question, context.source_text,
                additional_findings=context.semantic_findings, search_terms=context.search_terms)
            pages = set()
            offset = 0
            for page in context.document_pages:
                end = offset + len(page["text"])
                if any(start < end and offset < stop for start, stop in context.draft.source_spans):
                    pages.add(page["page"])
                offset = end + 2  # source_text joins pages with two newlines.
            context.selected_pages = tuple(sorted(pages))
            return context.draft.public_view()

        if call.name == "review_residual_risk":
            return self._review_residual(call.arguments, context, allow_repair=True)

        raise ToolValidationError("The model requested an unsupported tool.")

    def recheck_residual(self, raw_call: object, context: ToolContext) -> None:
        """One final check after automatic redaction; never authorize another repair."""
        call = validate_tool_call(raw_call)
        if call.name != "review_residual_risk" or not context.residual_recheck_required or context.executed_tools != list(_TOOL_ORDER):
            raise ToolValidationError("An unexpected residual recheck was requested.")
        try:
            self._review_residual(call.arguments, context, allow_repair=False)
        except PrivacyCheckError as exc:
            raise ToolValidationError("A residual recheck could not complete.") from exc

    def _review_residual(self, arguments: dict[str, Any], context: ToolContext, *, allow_repair: bool) -> dict[str, object]:
        if context.draft is None:
            raise ToolValidationError("A sanitized draft is required before residual review.")
        findings = validated_findings(context.draft.text, arguments.get("sensitive_spans", []))
        context.contextual_flags = tuple(arguments["risk_categories"])
        context.residual_recheck_required = False
        if findings:
            if allow_repair:
                context.draft = redact_remaining_values(context.draft, findings)
                context.semantic_findings += findings
                context.residual_recheck_required = True
            context.residual_review = ResidualReview("blocked", findings, (
                "Remaining identifying details require a fresh local check; edit or cancel if they cannot be verified.",
            ))
        else:
            context.residual_review = review_residual_risk(context.draft.text,
                contextual_flags=context.contextual_flags, contextual_review_complete=True)
            context.residual_review = review_outbound_identity(
                context.draft.text, context.source_text, context.question, context.residual_review,
                known_values=tuple(f._value for f in context.semantic_findings) if context.semantic_detection_complete else None)
        return context.residual_review.public_view()


_ARGUMENT_SCHEMAS: dict[str, dict[str, object]] = {
    "inspect_document": {
        "type": "object",
        "properties": {"terms": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8}},
        "required": ["terms"],
        "additionalProperties": False,
    },
    "detect_sensitive_data": {
        "type": "object",
        "properties": {"sensitive_spans": {"type": "array", "maxItems": MAX_SEMANTIC_FINDINGS,
            "items": {"type": "object", "properties": {
                "category": {"type": "string", "enum": sorted(SEMANTIC_CATEGORIES)},
                "value": {"type": "string", "minLength": 2, "maxLength": 500}},
                "required": ["category", "value"], "additionalProperties": False}}},
        "additionalProperties": False,
    },
    "select_relevant_content": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "propose_sanitized_request": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "review_residual_risk": {
        "type": "object",
        "properties": {
            "risk_categories": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(_RISK_CATEGORIES)},
                "maxItems": 6,
            }
        },
        "required": ["risk_categories"],
        "additionalProperties": False,
    },
}

# The residual reviewer can propose exact remaining draft spans for one bounded repair.
_ARGUMENT_SCHEMAS["review_residual_risk"]["properties"]["sensitive_spans"] = _ARGUMENT_SCHEMAS["detect_sensitive_data"]["properties"]["sensitive_spans"]
_ARGUMENT_SCHEMAS["detect_sensitive_data"]["properties"]["terms"] = _ARGUMENT_SCHEMAS["inspect_document"]["properties"]["terms"]

_DESCRIPTIONS = {
    "inspect_document": "Search only the document attached to the current workflow for concise relevant terms.",
    "detect_sensitive_data": "Inspect the bound document using terms and identify actual sensitive values as sensitive_spans. Quote exact source substrings: names, contact details, full addresses, lease/reference IDs, and identifying clues. Return an empty array if none are identified. The backend validates every value and combines them with deterministic detections.",
    "select_relevant_content": "Request selection of facts relevant to the user's existing question.",
    "propose_sanitized_request": "Request construction of a minimized draft using backend-validated privacy findings.",
    "review_residual_risk": "Review the sanitized draft only. risk_categories contains broad risks. sensitive_spans contains only exact unmasked identifying values still present in the draft, never placeholders or field labels. Use empty arrays when none remain.",
}


def ollama_tool_definitions() -> list[dict[str, object]]:
    """Return native Ollama function-tool definitions, not a prose convention."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": _DESCRIPTIONS[name],
                "parameters": _ARGUMENT_SCHEMAS[name],
            },
        }
        for name in _TOOL_ORDER
    ]


def _parse_arguments(raw: object, max_chars: int = MAX_TOOL_ARGUMENTS) -> dict[str, Any]:
    if isinstance(raw, str):
        if len(raw) > max_chars:
            raise ToolValidationError("Tool arguments exceed the configured size limit.")
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolValidationError("Tool arguments are malformed.") from exc
    try:
        encoded = json.dumps(raw, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ToolValidationError("Tool arguments are malformed.") from exc
    if len(encoded) > max_chars or not isinstance(raw, dict):
        raise ToolValidationError("Tool arguments are malformed or oversized.")
    return raw


def validate_tool_call(call: object) -> ValidatedToolCall:
    """Validate one Ollama native tool-call object against its exact schema."""
    if not isinstance(call, dict):
        raise ToolValidationError("The model returned a malformed tool call.")
    function = call.get("function")
    if not isinstance(function, dict):
        raise ToolValidationError("The model returned a malformed tool call.")
    name = function.get("name")
    if not isinstance(name, str) or name not in _ARGUMENT_SCHEMAS:
        raise ToolValidationError("The model requested an unsupported tool.")
    arguments = _parse_arguments(function.get("arguments"), 16_000 if name in {"detect_sensitive_data", "review_residual_risk"} else MAX_TOOL_ARGUMENTS)
    schema = _ARGUMENT_SCHEMAS[name]
    expected_fields = set(schema.get("required", []))
    if not expected_fields <= set(arguments) or not set(arguments) <= set(schema["properties"]):
        raise ToolValidationError("The model returned missing or unexpected tool fields.")

    if name == "inspect_document" or (name == "detect_sensitive_data" and "terms" in arguments):
        terms = arguments.get("terms")
        if (
            not isinstance(terms, list)
            or not 1 <= len(terms) <= 8
            or any(not isinstance(term, str) or not term.strip() or len(term) > 100 for term in terms)
        ):
            raise ToolValidationError("The document search terms are invalid.")
    if name == "detect_sensitive_data":
        if "terms" in arguments and "sensitive_spans" not in arguments:
            raise ToolValidationError("Combined inspection requires a detection result.")
        try:
            validate_candidates(arguments.get("sensitive_spans", []))
        except PrivacyCheckError as exc:
            raise ToolValidationError("Local identity detections are invalid.") from exc
    elif name == "review_residual_risk":
        try:
            validate_candidates(arguments.get("sensitive_spans", []))
        except PrivacyCheckError as exc:
            raise ToolValidationError("Residual identity detections are invalid.") from exc
        categories = arguments.get("risk_categories")
        if (
            not isinstance(categories, list)
            or len(categories) > 6
            or any(not isinstance(category, str) or category not in _RISK_CATEGORIES for category in categories)
        ):
            raise ToolValidationError("Residual-risk categories are invalid.")

    return ValidatedToolCall(name=name, arguments=arguments)


def validate_tool_sequence(calls: object) -> tuple[ValidatedToolCall, ...]:
    """Reject unknown, repeated, out-of-order, or excessive native tool calls."""
    if not isinstance(calls, list) or not 1 <= len(calls) <= MAX_TOOL_CALLS:
        raise ToolValidationError("The model returned an invalid number of tool calls.")
    validated = tuple(validate_tool_call(call) for call in calls)
    names = [call.name for call in validated]
    if len(set(names)) != len(names):
        raise ToolValidationError("A workflow tool cannot be called more than once.")
    if names != sorted(names, key=_TOOL_ORDER.index):
        raise ToolValidationError("The requested tools are out of workflow order.")
    return validated


def privacy_workflow_ready(context: ToolContext) -> bool:
    """True only after each required privacy tool completed for this workflow."""
    return (
        context.executed_tools == list(_TOOL_ORDER)
        and context.scan is not None
        and context.scan.complete
        and context.selected is not None
        and context.selected.status == "selected"
        and context.draft is not None
        and context.residual_review is not None
        and context.residual_review.status == "ready_for_user_review"
    )


def privacy_workflow_complete(context: ToolContext) -> bool:
    """True when all local steps ran, including a blocked result requiring edits."""
    return (
        context.executed_tools == list(_TOOL_ORDER)
        and context.scan is not None
        and context.scan.complete
        and context.selected is not None
        and context.selected.status == "selected"
        and context.draft is not None
        and context.residual_review is not None
        and context.residual_review.status in {"ready_for_user_review", "needs_review", "blocked"}
    )
