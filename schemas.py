"""Pydantic request / response models for POST /api/classify.

Kept separate from app.py so the schemas are re-usable (docs, tests, other
consumers) without dragging in the FastAPI app object.
"""

from typing import Optional
from pydantic import BaseModel, Field


# ---------- Request ----------

class AttachmentIn(BaseModel):
    filename: str = Field(..., min_length=1, description="Original filename incl. extension")
    content_base64: str = Field(..., description="Base64-encoded file bytes")


class ClassifyRequest(BaseModel):
    sender_domain: str = Field(..., min_length=1, description="e.g. brightleafretail.com")
    subject: str = Field(..., description="Email subject line")
    body: str = Field("", description="Plain-text email body (optional)")
    attachments: list[AttachmentIn] = Field(
        default_factory=list,
        description="One or more attachments. Phase 7 caps this at 1; "
                    "Phase 5 will lift the cap without shape churn.",
    )


# ---------- Response ----------

class RoutingHints(BaseModel):
    sharepoint_folder: str
    monday_board_hint: str
    monday_group_hint: Optional[str]
    priority_hint: str  # "high" | "normal"


class AttachmentResult(BaseModel):
    filename: str
    label: str
    confidence: float
    rationale: str
    identifier: Optional[str]
    identifier_rationale: str
    identifier_candidates: list[str]
    keyword_hits: list[str]
    needs_review: bool
    routing: RoutingHints


class EmailContext(BaseModel):
    sender_domain: str
    subject: str
    body_length: int


class Summary(BaseModel):
    attachment_count: int
    distinct_identifiers: list[str]
    distinct_categories: list[str]
    should_fan_out: bool
    any_needs_review: bool


class ClassifyResponse(BaseModel):
    email: EmailContext
    attachments: list[AttachmentResult]
    summary: Summary
    model: str


# ---------- Error envelope ----------

class ApiError(BaseModel):
    error: str
    code: str
