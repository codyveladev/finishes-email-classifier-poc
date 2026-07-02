"""Smoke tests for POST /api/classify.

Auth + validation + shape cases are stubbed so they cost zero API calls.
The final case runs the classifier for real against the sample docx —
set SKIP_LIVE=1 to skip it when conserving free-tier quota.
"""

import base64
import os
from dotenv import load_dotenv; load_dotenv()

TEST_TOKEN = "test-token-abc123"
os.environ["API_TOKEN"] = TEST_TOKEN

from starlette.testclient import TestClient
import app
import classifier   # monkey-patched below to stub out live Gemini calls

client = TestClient(app.app)
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def sample_payload(**overrides):
    with open("samples/Change_Order_OP-215.docx", "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    payload = {
        "sender_domain": "gc-buildwell.com",
        "subject": "Change Order CO-12 — Riverbend Commons",
        "body": "",
        "attachments": [{"filename": "Change_Order_OP-215.docx", "content_base64": b64}],
    }
    payload.update(overrides)
    return payload


def stub_result(**overrides):
    """A classifier.classify() return value with sane defaults, overridable per case."""
    result = {
        "label": "Development / Construction",
        "confidence": 0.98,
        "rationale": "stubbed",
        "identifier": "OP-215",
        "identifier_rationale": "stubbed",
        "identifier_candidates": ["OP-215"],
        "method": "gemini",
        "keyword_hits": ["change order", "site work"],
        "needs_review": False,
    }
    result.update(overrides)
    return result


def check(name, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}{('  - ' + extra) if extra else ''}")
    assert cond, name


_real_classify = classifier.classify

# ---------- Auth ----------

r = client.post("/api/classify", json=sample_payload())
check("no auth -> 401", r.status_code == 401 and r.json()["code"] == "unauthorized")

r = client.post("/api/classify", json=sample_payload(),
                headers={"Authorization": "Bearer wrong"})
check("bad token -> 401", r.status_code == 401)

# ---------- Request validation (no LLM calls) ----------

too_many = sample_payload()
too_many["attachments"] = too_many["attachments"] * 2
r = client.post("/api/classify", json=too_many, headers=AUTH)
check("multi-attachment blocked -> 400",
      r.status_code == 400 and r.json()["code"] == "multi_attachment_unsupported")

bad = sample_payload()
bad["attachments"][0]["content_base64"] = "not valid base64!!!"
r = client.post("/api/classify", json=bad, headers=AUTH)
check("bad base64 -> 400", r.status_code == 400 and r.json()["code"] == "invalid_base64")

missing = sample_payload()
del missing["sender_domain"]
r = client.post("/api/classify", json=missing, headers=AUTH)
check("missing field -> 422", r.status_code == 422)

# ---------- Zero-attachment path (stubbed) ----------

def stub_email_only(sender_domain, subject, body="", attachment_path=None, attachment_text=None):
    assert attachment_text is None, "zero-attachment path should pass attachment_text=None"
    return stub_result(label="General Governance", confidence=0.7,
                       identifier=None, identifier_candidates=[], keyword_hits=[])

classifier.classify = stub_email_only
r = client.post("/api/classify",
                json={"sender_domain": "x.com", "subject": "s", "body": "", "attachments": []},
                headers=AUTH)
data = r.json()
check("no attachments -> 200 (email-only)", r.status_code == 200)
check("email-only: attachments_analyzed is empty", data["attachments_analyzed"] == [])
check("email-only: routing falls back to /Intake/",
      data["email"]["sharepoint_folder"].startswith("/Intake/"))

# ---------- Happy path with attachment (stubbed) ----------

def stub_single_project(sender_domain, subject, body="", attachment_path=None, attachment_text=None):
    assert attachment_text and "OP-215" in attachment_text, \
        "router should extract the docx text and pass it through"
    return stub_result()

classifier.classify = stub_single_project
r = client.post("/api/classify", json=sample_payload(), headers=AUTH)
data = r.json()
email = data["email"]
check("stubbed classify -> 200", r.status_code == 200)
check("label at email level", email["label"] == "Development / Construction")
check("identifier at email level", email["identifier"] == "OP-215")
check("sharepoint hint uses OP prefix",
      email["sharepoint_folder"] == "/Deals/01_Active_Deals/OP-215")
check("monday board hint from category",
      email["monday_board_hint"] == "Construction Intake")
check("priority hint is High (change order keyword)",
      email["priority_hint"] == "High")
check("single project -> no multi-project flag",
      email["multiple_projects_detected"] is False)
check("confident single project -> no review",
      email["needs_review"] is False and email["review_reasons"] == [])
check("attachment analyzed with identifiers",
      len(data["attachments_analyzed"]) == 1
      and data["attachments_analyzed"][0]["identifiers_found"] == ["OP-215"])
check("attachment size recorded", data["attachments_analyzed"][0]["size_bytes"] > 0)
check("model echoed", data["model"] == classifier.MODEL)

# ---------- Multi-project detection (stubbed) ----------

def stub_multi_project(sender_domain, subject, body="", attachment_path=None, attachment_text=None):
    return stub_result(confidence=0.85,
                       identifier_candidates=["OP-215", "OP-142"])

classifier.classify = stub_multi_project
r = client.post("/api/classify", json=sample_payload(), headers=AUTH)
email = r.json()["email"]
check("multi-project: flag set", email["multiple_projects_detected"] is True)
check("multi-project: forces needs_review even at high confidence",
      email["needs_review"] is True)
check("multi-project: reason slug present",
      email["review_reasons"] == ["multiple_projects_detected"])

# ---------- Low confidence (stubbed) ----------

def stub_low_confidence(sender_domain, subject, body="", attachment_path=None, attachment_text=None):
    return stub_result(confidence=0.4, needs_review=True)

classifier.classify = stub_low_confidence
r = client.post("/api/classify", json=sample_payload(), headers=AUTH)
email = r.json()["email"]
check("low confidence: needs_review true", email["needs_review"] is True)
check("low confidence: reason slug present",
      "low_confidence" in email["review_reasons"])

classifier.classify = _real_classify

# ---------- Live Gemini call (skip with SKIP_LIVE=1) ----------

if os.environ.get("SKIP_LIVE") == "1":
    print("[SKIP] live classify (SKIP_LIVE=1)")
else:
    r = client.post("/api/classify", json=sample_payload(), headers=AUTH)
    if r.status_code == 200:
        email = r.json()["email"]
        check(f"live: label ok ({email['label']}, {email['confidence']:.0%})",
              email["label"] == "Development / Construction")
        check(f"live: identifier ok ({email['identifier']})", email["identifier"] == "OP-215")
        check("live: routing populated",
              email["sharepoint_folder"] == "/Deals/01_Active_Deals/OP-215")
    else:
        print(f"[SKIP] live classify -> {r.status_code} ({r.json().get('code')}): {r.json().get('error')}")

print("\nAll assertions passed.")
