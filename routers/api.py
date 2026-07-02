"""JSON webhook API: POST /api/classify.

The email is the unit of classification: one call → one label + identifier +
routing hints, ready to become one Monday intake item. Attachments are read
as evidence and individually scanned for project identifiers so the response
can flag multi-project emails for human triage — but they are never
individually classified.
"""

import base64

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

import classifier
import routing
from attachment_io import temp_file_from_bytes
from config import Settings, get_settings
from dependencies import verify_bearer
from errors import api_error_response, classifier_exception_to_api_response
from extract import extract_text
from schemas import (
    AttachmentAnalyzed, ClassifyRequest, ClassifyResponse, EmailResult,
)


router = APIRouter(
    tags=["classifier"],
    dependencies=[Depends(verify_bearer)],
)

# Machine-readable slugs for EmailResult.review_reasons. Downstream branches
# on these; keep them stable once orchestrators depend on them.
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_MULTIPLE_PROJECTS = "multiple_projects_detected"


@router.post("/classify", response_model=ClassifyResponse)
def classify_email(
    payload: ClassifyRequest,
    settings: Settings = Depends(get_settings),
) -> ClassifyResponse | JSONResponse:
    if len(payload.attachments) > 1:
        return api_error_response(
            400, "multi_attachment_unsupported",
            "Attachments are currently capped at 1 per request. "
            "Multi-attachment support is Phase 5.",
        )

    att_in = payload.attachments[0] if payload.attachments else None

    # Decode + validate the attachment before spending an LLM call on it.
    attachment_bytes: bytes | None = None
    if att_in is not None:
        try:
            attachment_bytes = base64.b64decode(att_in.content_base64, validate=True)
        except Exception:
            return api_error_response(
                400, "invalid_base64",
                f"attachments[0].content_base64 could not be decoded for '{att_in.filename}'.",
            )
        if len(attachment_bytes) > settings.max_attachment_bytes:
            return api_error_response(
                413, "attachment_too_large",
                f"'{att_in.filename}' is {len(attachment_bytes)} bytes; "
                f"the limit is {settings.max_attachment_bytes}.",
            )

    # Extract attachment text here (rather than inside classify) so we can
    # scan each file for identifiers independently — that per-file view is
    # what lets a reviewer see WHICH attachment references WHICH project.
    attachments_analyzed: list[AttachmentAnalyzed] = []
    attachment_text: str | None = None
    if att_in is not None and attachment_bytes is not None:
        with temp_file_from_bytes(attachment_bytes, att_in.filename) as tmp_path:
            attachment_text = extract_text(str(tmp_path))
        attachments_analyzed.append(AttachmentAnalyzed(
            filename=att_in.filename,
            size_bytes=len(attachment_bytes),
            identifiers_found=classifier.find_identifiers(attachment_text),
        ))

    # One classification for the whole email; attachment text rides along as
    # evidence. attachment_text=None means subject + body only.
    try:
        result = classifier.classify(
            payload.sender_domain, payload.subject, payload.body,
            attachment_text=attachment_text,
        )
    except Exception as e:  # noqa: BLE001 — every failure type maps to a structured error
        return classifier_exception_to_api_response(e)

    hints = routing.compute_routing(
        label=result["label"],
        identifier=result["identifier"],
        keyword_hits=result["keyword_hits"],
        sender_domain=payload.sender_domain,
    )

    # Triage flags. identifier_candidates already spans subject + body +
    # attachment text, so >1 distinct code means this email touches more than
    # one project — the human decides whether to split at approval time.
    review_reasons: list[str] = []
    if result["needs_review"]:
        review_reasons.append(REASON_LOW_CONFIDENCE)
    multiple_projects = len(result["identifier_candidates"]) > 1
    if multiple_projects:
        review_reasons.append(REASON_MULTIPLE_PROJECTS)

    email_result = EmailResult(
        sender_domain=payload.sender_domain,
        subject=payload.subject,
        body_length=len(payload.body),
        label=result["label"],
        confidence=result["confidence"],
        rationale=result["rationale"],
        identifier=result["identifier"],
        identifier_rationale=result["identifier_rationale"],
        identifier_candidates=result["identifier_candidates"],
        keyword_hits=result["keyword_hits"],
        priority_hint=hints["priority_hint"],
        monday_board_hint=hints["monday_board_hint"],
        monday_group_hint=hints["monday_group_hint"],
        sharepoint_folder=hints["sharepoint_folder"],
        multiple_projects_detected=multiple_projects,
        needs_review=bool(review_reasons),
        review_reasons=review_reasons,
    )

    return ClassifyResponse(
        email=email_result,
        attachments_analyzed=attachments_analyzed,
        model=classifier.MODEL,
    )
