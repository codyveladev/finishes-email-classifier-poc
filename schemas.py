"""Pydantic request / response models for POST /api/classify.

Shape philosophy: the EMAIL is the unit of classification. One email in,
one label + one identifier + one set of routing hints out. Attachments are
evidence the classifier reads — they are analyzed (identifier scan) but never
individually classified, because downstream creates one intake item per email.
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
        description="Attachments to read as classification evidence. "
                    "Empty list = classify from subject + body alone. "
                    "Currently capped at 1; Phase 5 lifts the cap.",
    )


# ---------- Response ----------

class EmailResult(BaseModel):
    """The single classification record for this email — everything a
    downstream orchestrator needs to create one Monday intake item."""

    # Echo of the request, so later Zap/flow steps don't re-read earlier steps.
    sender_domain: str
    subject: str
    body_length: int

    # Classification (LLM).
    label: str
    confidence: float                       # model self-report; use needs_review for decisions
    rationale: str

    # Project / asset identifier (regex candidates, LLM picks the best).
    identifier: Optional[str]               # e.g. "OP-215" (Deal) or "AS-087" (Asset)
    identifier_rationale: str
    identifier_candidates: list[str]        # every code found across subject/body/attachments

    # Evidence + routing hints (deterministic, computed in routing.py).
    keyword_hits: list[str]
    priority_hint: str                      # "High" | "Normal" — cased to match Monday status labels
    monday_board_hint: str
    monday_group_hint: Optional[str]
    sharepoint_folder: str                  # suggested destination for ALL attachments on this email

    # Triage flags.
    multiple_projects_detected: bool        # >1 distinct identifier found — human should consider splitting
    needs_review: bool                      # true if ANY review_reasons entry exists
    needs_review_text: str                  # "Yes" | "No" — same flag, cased for Monday status columns
    review_reasons: list[str]               # machine-readable slugs, e.g. ["low_confidence"]


class AttachmentAnalyzed(BaseModel):
    """Audit record of one attachment the classifier ingested. Deliberately
    carries no label or confidence — attachments are evidence, not outputs.
    identifiers_found tells the reviewer which file references which project,
    which is what makes a multi-project split actionable."""
    filename: str
    size_bytes: int
    identifiers_found: list[str]            # regex hits within THIS file's text only


class ClassifyResponse(BaseModel):
    email: EmailResult
    attachments_analyzed: list[AttachmentAnalyzed]
    model: str


# ---------- Error envelope ----------

class ApiError(BaseModel):
    error: str
    code: str
