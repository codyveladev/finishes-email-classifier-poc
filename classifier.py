"""Core classifier: keyword pre-pass + structured Gemini call."""

import re
from typing import Literal, Optional
from pydantic import BaseModel
from google import genai

from extract import extract_text
from categories import keyword_hits

# OP-#### = Deal (3-4+ digit project codes), AS-### = Asset.
IDENTIFIER_RE = re.compile(r"\b(OP|AS)-(\d{3,})\b", re.IGNORECASE)


def find_identifiers(text: str) -> list[str]:
    """Return all OP-#### / AS-### candidates in the text, deduped, order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for m in IDENTIFIER_RE.finditer(text):
        ident = f"{m.group(1).upper()}-{m.group(2)}"
        if ident not in seen:
            seen.add(ident)
            out.append(ident)
    return out

MODEL = "gemini-2.5-flash"
CONFIDENCE_THRESHOLD = 0.60

Label = Literal[
    "Development / Construction",
    "Payment / Billing",
    "Lease / Occupancy",
    "Compliance / Legal",
    "Capital / Finance",
    "Vendor Performance",
    "General Governance",
]


class Classification(BaseModel):
    label: Label
    confidence: float
    rationale: str
    identifier: Optional[str]          # e.g. "OP-142" (Deal) or "AS-087" (Asset); null if none
    identifier_rationale: str          # one-line explanation; "no identifier found" if null


client = genai.Client()

PROMPT = (
    "You classify real-estate / property-management emails into exactly one "
    "category. Use the sender domain, subject, keyword hits, and attachment "
    "text. Return the single best label, a confidence from 0 to 1, and a "
    "one-sentence rationale.\n\n"
    "Category guidance:\n"
    "- Development / Construction: active construction work — change orders, "
    "RFIs, submittals, contractor coordination, drawings, mobilization.\n"
    "- Payment / Billing: invoices, receipts, statements, remittances, money owed.\n"
    "- Lease / Occupancy: lease agreements, tenant/landlord matters, rent, "
    "estoppels, CAM, renewals, vacancy.\n"
    "- Compliance / Legal: permits, licenses, regulatory approvals, zoning, "
    "violations, legal counsel, insurance certificates. A permit issued or "
    "approved by a government office is Compliance / Legal, even if the "
    "underlying work is construction.\n"
    "- Capital / Finance: capital calls, equity/debt, loans, refinancing, "
    "budgets, investor distributions.\n"
    "- Vendor Performance: vendor/supplier service agreements, SLAs, scopes "
    "of work, maintenance contracts, work orders, KPIs.\n"
    "- General Governance: board minutes, policies, memos, resolutions, "
    "internal correspondence (default catch-all).\n\n"
    "Identifier extraction:\n"
    "- OP-#### codes (e.g. OP-142) identify a Deal.\n"
    "- AS-### codes (e.g. AS-087) identify an Asset.\n"
    "- The IDENTIFIER CANDIDATES line lists every match the regex pre-pass found. "
    "Pick the one that best identifies what this email is about. Usually that "
    "is the code mentioned in the subject or the first one referenced in the "
    "attachment. If no candidates are listed, return null and say so in "
    "identifier_rationale.\n\n"
)


def build_signal(sender_domain: str, subject: str, body: str,
                 attachment_path: Optional[str],
                 attachment_text: Optional[str] = None) -> tuple[str, list[str], list[str]]:
    # attachment_text lets callers that already extracted the file (e.g. the API
    # router, which scans each attachment for identifiers) skip a second extraction.
    if attachment_text is not None:
        att = attachment_text
    else:
        att = extract_text(attachment_path) if attachment_path else ""
    combined = f"{subject}\n{body}\n{att}"
    hits = keyword_hits(combined)
    ids = find_identifiers(combined)
    signal = (
        f"SENDER DOMAIN: {sender_domain}\n"
        f"SUBJECT: {subject}\n"
        f"BODY: {body}\n"
        f"KEYWORD HITS: {hits}\n"
        f"IDENTIFIER CANDIDATES: {ids}\n"
        f"ATTACHMENT TEXT (truncated):\n{att[:6000]}"
    )
    return signal, hits, ids


def classify(sender_domain: str, subject: str, body: str = "",
             attachment_path: Optional[str] = None,
             attachment_text: Optional[str] = None) -> dict:
    signal, hits, ids = build_signal(sender_domain, subject, body,
                                     attachment_path, attachment_text)
    resp = client.models.generate_content(
        model=MODEL,
        contents=PROMPT + signal,
        config={
            "response_mime_type": "application/json",
            "response_schema": Classification,
            "temperature": 0,
        },
    )
    result = Classification.model_validate_json(resp.text)
    return {
        "label": result.label,
        "confidence": round(result.confidence, 2),
        "rationale": result.rationale,
        "identifier": result.identifier,
        "identifier_rationale": result.identifier_rationale,
        "identifier_candidates": ids,
        "method": "gemini",
        "keyword_hits": hits,
        "needs_review": result.confidence < CONFIDENCE_THRESHOLD,
    }
