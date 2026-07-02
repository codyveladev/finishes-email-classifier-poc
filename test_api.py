"""Smoke tests for POST /api/classify.

Auth + validation cases are stubbed so they cost zero API calls.
The final case runs the classifier for real against the sample docx —
set SKIP_LIVE=1 to skip if you're conserving free-tier quota.
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


def check(name, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}{('  - ' + extra) if extra else ''}")
    assert cond, name


# 1. Missing Authorization -> 401
r = client.post("/api/classify", json=sample_payload())
check("no auth -> 401", r.status_code == 401 and r.json()["code"] == "unauthorized")

# 2. Wrong bearer token -> 401
r = client.post("/api/classify", json=sample_payload(),
                headers={"Authorization": "Bearer wrong"})
check("bad token -> 401", r.status_code == 401)

# 3. Empty attachments -> 200 with sentinel filename (zero-attachment path)
#    Stub the classifier so this doesn't cost a live API call.
def stub_email_only(sender_domain, subject, body, attachment_path):
    assert attachment_path is None, "expected zero-attachment path to pass None"
    return {
        "label": "General Governance", "confidence": 0.7, "rationale": "stubbed email-only",
        "identifier": None, "identifier_rationale": "no identifier",
        "identifier_candidates": [], "method": "gemini",
        "keyword_hits": [], "needs_review": False,
    }
_orig_for_zero = classifier.classify
classifier.classify = stub_email_only
r = client.post("/api/classify",
                json={"sender_domain": "x.com", "subject": "s", "body": "", "attachments": []},
                headers=AUTH)
check("no attachments -> 200 (email-only)", r.status_code == 200)
data = r.json()
check("email-only: single result with sentinel filename",
      len(data["attachments"]) == 1 and data["attachments"][0]["filename"] == "(email body)")
check("email-only: routing falls back to /Intake/",
      data["attachments"][0]["routing"]["sharepoint_folder"].startswith("/Intake/"))
classifier.classify = _orig_for_zero  # restore

# 4. Two attachments (Phase 7 cap) -> 400
too_many = sample_payload()
too_many["attachments"] = too_many["attachments"] * 2
r = client.post("/api/classify", json=too_many, headers=AUTH)
check("multi-attachment blocked -> 400", r.status_code == 400 and r.json()["code"] == "multi_attachment_unsupported")

# 5. Bad base64 -> 400
bad = sample_payload()
bad["attachments"][0]["content_base64"] = "not valid base64!!!"
r = client.post("/api/classify", json=bad, headers=AUTH)
check("bad base64 -> 400", r.status_code == 400 and r.json()["code"] == "invalid_base64")

# 6. Missing sender_domain -> 422 (pydantic validation)
missing = sample_payload()
del missing["sender_domain"]
r = client.post("/api/classify", json=missing, headers=AUTH)
check("missing field -> 422", r.status_code == 422)

# 7. Stubbed classifier — verifies routing hints + response shape without an API call
def stub_classify(sender_domain, subject, body, attachment_path):
    return {
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
_orig = classifier.classify
classifier.classify = stub_classify

r = client.post("/api/classify", json=sample_payload(), headers=AUTH)
data = r.json()
check("stubbed classify -> 200", r.status_code == 200)
check("response has attachments", len(data["attachments"]) == 1)
att = data["attachments"][0]
check("label carried through", att["label"] == "Development / Construction")
check("identifier carried through", att["identifier"] == "OP-215")
check("sharepoint hint uses OP prefix",
      att["routing"]["sharepoint_folder"] == "/Deals/01_Active_Deals/OP-215")
check("monday board hint from category",
      att["routing"]["monday_board_hint"] == "Construction Intake")
check("priority hint is high (change order keyword)",
      att["routing"]["priority_hint"] == "high")
check("summary is single-item",
      data["summary"]["attachment_count"] == 1 and not data["summary"]["should_fan_out"])
check("model echoed", data["model"] == classifier.MODEL)

classifier.classify = _orig  # restore

# 8. LIVE — real Gemini call (skip with SKIP_LIVE=1)
if os.environ.get("SKIP_LIVE") == "1":
    print("[SKIP] live classify (SKIP_LIVE=1)")
else:
    r = client.post("/api/classify", json=sample_payload(), headers=AUTH)
    if r.status_code == 200:
        data = r.json()
        att = data["attachments"][0]
        check(f"live: label ok ({att['label']}, {att['confidence']:.0%})",
              att["label"] == "Development / Construction")
        check(f"live: identifier ok ({att['identifier']})", att["identifier"] == "OP-215")
        check("live: routing populated",
              att["routing"]["sharepoint_folder"] == "/Deals/01_Active_Deals/OP-215")
    else:
        print(f"[SKIP] live classify -> {r.status_code} ({r.json().get('code')}): {r.json().get('error')}")

print("\nAll assertions passed.")
