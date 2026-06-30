"""Core classifier: keyword pre-pass + structured Gemini call."""

from typing import Literal, Optional
from pydantic import BaseModel
from google import genai

from extract import extract_text
from categories import keyword_hits

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
)


def build_signal(sender_domain: str, subject: str, body: str,
                 attachment_path: Optional[str]) -> tuple[str, list[str]]:
    att = extract_text(attachment_path) if attachment_path else ""
    hits = keyword_hits(f"{subject}\n{body}\n{att}")
    signal = (
        f"SENDER DOMAIN: {sender_domain}\n"
        f"SUBJECT: {subject}\n"
        f"BODY: {body}\n"
        f"KEYWORD HITS: {hits}\n"
        f"ATTACHMENT TEXT (truncated):\n{att[:6000]}"
    )
    return signal, hits


def classify(sender_domain: str, subject: str, body: str = "",
             attachment_path: Optional[str] = None) -> dict:
    signal, hits = build_signal(sender_domain, subject, body, attachment_path)
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
        "method": "gemini",
        "keyword_hits": hits,
        "needs_review": result.confidence < CONFIDENCE_THRESHOLD,
    }
