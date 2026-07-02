"""JSON webhook API: POST /api/classify.

Wraps classifier.classify() and layers routing hints so external orchestrators
(Zapier, Power Automate) can drive the intake flow without further logic.
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
from schemas import (
    AttachmentResult, ClassifyRequest, ClassifyResponse,
    EmailContext, RoutingHints, Summary,
)


router = APIRouter(
    tags=["classifier"],
    dependencies=[Depends(verify_bearer)],
)


@router.post("/classify", response_model=ClassifyResponse)
def classify_email(
    payload: ClassifyRequest,
    settings: Settings = Depends(get_settings),
) -> ClassifyResponse | JSONResponse:
    if len(payload.attachments) > 1:
        return api_error_response(
            400, "multi_attachment_unsupported",
            "Phase 7 caps attachments at 1. Multi-attachment is Phase 5.",
        )

    # Zero-attachment path: classify subject + body only.
    # Sentinel filename in the result keeps the response shape uniform for
    # downstream consumers that always read from attachments[0].
    att_in = payload.attachments[0] if payload.attachments else None
    display_filename = "(email body)"
    attachment_bytes: bytes | None = None

    if att_in is not None:
        display_filename = att_in.filename
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

    try:
        if attachment_bytes is not None:
            with temp_file_from_bytes(attachment_bytes, att_in.filename) as tmp_path:
                result = classifier.classify(
                    payload.sender_domain, payload.subject, payload.body, str(tmp_path),
                )
        else:
            result = classifier.classify(
                payload.sender_domain, payload.subject, payload.body, None,
            )
    except Exception as e:  # noqa: BLE001 — mapped through classifier_exception_to_api_response
        return classifier_exception_to_api_response(e)

    hints = routing.compute_routing(
        label=result["label"],
        identifier=result["identifier"],
        keyword_hits=result["keyword_hits"],
        sender_domain=payload.sender_domain,
    )

    att_result = AttachmentResult(
        filename=display_filename,
        label=result["label"],
        confidence=result["confidence"],
        rationale=result["rationale"],
        identifier=result["identifier"],
        identifier_rationale=result["identifier_rationale"],
        identifier_candidates=result["identifier_candidates"],
        keyword_hits=result["keyword_hits"],
        needs_review=result["needs_review"],
        routing=RoutingHints(**hints),
    )

    distinct_ids = [att_result.identifier] if att_result.identifier else []
    distinct_cats = [att_result.label]

    return ClassifyResponse(
        email=EmailContext(
            sender_domain=payload.sender_domain,
            subject=payload.subject,
            body_length=len(payload.body),
        ),
        attachments=[att_result],
        summary=Summary(
            attachment_count=1,
            distinct_identifiers=distinct_ids,
            distinct_categories=distinct_cats,
            should_fan_out=False,   # single attachment; Phase 5 computes real value
            any_needs_review=att_result.needs_review,
        ),
        model=classifier.MODEL,
    )
