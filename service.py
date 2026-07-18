"""Classification pipeline shared by the JSON and multipart API routes.

Both routes normalize their very different inputs (base64 strings vs. multipart
uploads) into a list of IncomingFile, then hand off here. Everything below is
transport-agnostic.
"""

from dataclasses import dataclass

import classifier
import routing
from attachment_io import temp_file_from_bytes
from extract import extract_text
from schemas import AttachmentAnalyzed, ClassifyResponse, EmailResult

# Stable slugs for EmailResult.review_reasons. Orchestrators branch on these;
# don't rename them once a Zap or Power Automate flow depends on them.
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_MULTIPLE_PROJECTS = "multiple_projects_detected"
REASON_UNCLASSIFIED = "unclassified"

# The catch-all label. When the model lands here it could not place the email,
# so it always warrants a human look regardless of self-reported confidence.
UNCLASSIFIED_LABEL = "Unclassified"


@dataclass(frozen=True)
class IncomingFile:
    filename: str
    data: bytes


def _combine_attachment_text(parts: list[tuple[str, str]]) -> str:
    """Label each attachment's text so the model can attribute evidence to a
    specific file, and split the prompt budget evenly so one long attachment
    can't crowd the others out of the signal entirely."""
    per_file = classifier.ATTACHMENT_TEXT_BUDGET // len(parts)
    return "\n".join(
        f"--- ATTACHMENT: {filename} ---\n{text[:per_file]}"
        for filename, text in parts
    )


def _collect_identifiers(subject: str, body: str,
                         parts: list[tuple[str, str]]) -> list[str]:
    """Union of every OP-###/AS-### across the email and each attachment's FULL
    text — deliberately not the budget-trimmed prompt text, so a code buried
    deep in a long document still reaches the reviewer."""
    found = classifier.find_identifiers(f"{subject}\n{body}")
    for _, text in parts:
        for ident in classifier.find_identifiers(text):
            if ident not in found:
                found.append(ident)
    return found


def run_classification(sender_domain: str, subject: str, body: str,
                       files: list[IncomingFile]) -> ClassifyResponse:
    analyzed: list[AttachmentAnalyzed] = []
    text_parts: list[tuple[str, str]] = []

    for f in files:
        with temp_file_from_bytes(f.data, f.filename) as tmp_path:
            text = extract_text(str(tmp_path))
        text_parts.append((f.filename, text))
        analyzed.append(AttachmentAnalyzed(
            filename=f.filename,
            size_bytes=len(f.data),
            identifiers_found=classifier.find_identifiers(text),
        ))

    all_identifiers = _collect_identifiers(subject, body, text_parts)
    combined_text = _combine_attachment_text(text_parts) if text_parts else None

    result = classifier.classify(
        sender_domain, subject, body,
        attachment_text=combined_text,
        identifier_candidates=all_identifiers,
    )

    hints = routing.compute_routing(
        label=result["label"],
        identifier=result["identifier"],
        keyword_hits=result["keyword_hits"],
        sender_domain=sender_domain,
    )

    review_reasons: list[str] = []
    if result["needs_review"]:
        review_reasons.append(REASON_LOW_CONFIDENCE)
    # More than one project code across the email means a reviewer should decide
    # whether to split the intake item — worth flagging even when the model is
    # confident about the category.
    multiple_projects = len(all_identifiers) > 1
    if multiple_projects:
        review_reasons.append(REASON_MULTIPLE_PROJECTS)
    # The model couldn't place the email — always a human's call, even if it
    # reported high confidence in giving up.
    if result["label"] == UNCLASSIFIED_LABEL:
        review_reasons.append(REASON_UNCLASSIFIED)

    email_result = EmailResult(
        sender_domain=sender_domain,
        subject=subject,
        body_length=len(body),
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
        needs_review_text="Yes" if review_reasons else "No",
        review_reasons=review_reasons,
    )

    return ClassifyResponse(
        email=email_result,
        attachments_analyzed=analyzed,
        model=classifier.MODEL,
    )
