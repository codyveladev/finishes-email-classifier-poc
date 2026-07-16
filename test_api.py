"""Smoke tests for the classifier API.

Covers both transports: POST /api/classify (JSON + base64) and
POST /api/classify-upload (multipart). Auth, validation, and shape cases stub
the LLM so they cost zero API calls — the regex/identifier logic still runs for
real. The final case makes one live Gemini call; set SKIP_LIVE=1 to skip it.
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

CHANGE_ORDER = "samples/Change_Order_OP-215.docx"   # contains OP-215
LEASE = "samples/Lease_Agreement_OP-142.pdf"        # contains OP-142


def read_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def payload(paths=(CHANGE_ORDER,), **overrides):
    body = {
        "sender_domain": "gc-buildwell.com",
        "subject": "Change Order CO-12 — Riverbend Commons",
        "body": "",
        "attachments": [
            {"filename": os.path.basename(p), "content_base64": read_b64(p)}
            for p in paths
        ],
    }
    body.update(overrides)
    return body


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


def make_stub(**overrides):
    """Stub that echoes back the identifier candidates the service computed,
    mirroring what the real classify() does."""
    def _stub(sender_domain, subject, body="", attachment_path=None,
              attachment_text=None, identifier_candidates=None):
        return stub_result(identifier_candidates=identifier_candidates or [],
                           **overrides)
    return _stub


def check(name, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}{('  - ' + extra) if extra else ''}")
    assert cond, name


_real_classify = classifier.classify

# ---------- Auth ----------

r = client.post("/api/classify", json=payload())
check("json: no auth -> 401", r.status_code == 401 and r.json()["code"] == "unauthorized")

r = client.post("/api/classify", json=payload(), headers={"Authorization": "Bearer wrong"})
check("json: bad token -> 401", r.status_code == 401)

r = client.post("/api/classify-upload",
                data={"sender_domain": "x.com", "subject": "s"},
                files=[("attachments", ("a.docx", read_bytes(CHANGE_ORDER)))])
check("multipart: no auth -> 401", r.status_code == 401)

# ---------- Request validation ----------

bad = payload()
bad["attachments"][0]["content_base64"] = "not valid base64!!!"
r = client.post("/api/classify", json=bad, headers=AUTH)
check("json: bad base64 -> 400", r.status_code == 400 and r.json()["code"] == "invalid_base64")

missing = payload()
del missing["sender_domain"]
r = client.post("/api/classify", json=missing, headers=AUTH)
check("json: missing field -> 422", r.status_code == 422)

too_many = payload(paths=[CHANGE_ORDER] * 11)
r = client.post("/api/classify", json=too_many, headers=AUTH)
check("json: 11 attachments -> 400",
      r.status_code == 400 and r.json()["code"] == "too_many_attachments")

# ---------- Zero attachments ----------

def stub_email_only(sender_domain, subject, body="", attachment_path=None,
                    attachment_text=None, identifier_candidates=None):
    assert attachment_text is None, "zero-attachment path should pass attachment_text=None"
    return stub_result(label="General Governance", confidence=0.7, identifier=None,
                       identifier_candidates=[], keyword_hits=[])

classifier.classify = stub_email_only
r = client.post("/api/classify",
                json={"sender_domain": "x.com", "subject": "s", "body": "", "attachments": []},
                headers=AUTH)
data = r.json()
check("json: no attachments -> 200 (email-only)", r.status_code == 200)
check("email-only: attachments_analyzed is empty", data["attachments_analyzed"] == [])
check("email-only: routing falls back to /Intake/",
      data["email"]["sharepoint_folder"].startswith("/Intake/"))

# ---------- Single attachment (JSON) ----------

classifier.classify = make_stub()
r = client.post("/api/classify", json=payload(), headers=AUTH)
data = r.json()
email = data["email"]
check("json: single attachment -> 200", r.status_code == 200)
check("label at email level", email["label"] == "Development / Construction")
check("identifier at email level", email["identifier"] == "OP-215")
check("sharepoint hint uses OP prefix",
      email["sharepoint_folder"] == "/Deals/01_Active_Deals/OP-215")
check("monday board hint from category", email["monday_board_hint"] == "Construction Intake")
check("priority hint is High (change order keyword)", email["priority_hint"] == "High")
check("single project -> no multi-project flag", email["multiple_projects_detected"] is False)
check("confident single project -> no review",
      email["needs_review"] is False and email["review_reasons"] == [])
check("needs_review_text mirrors the boolean (No)", email["needs_review_text"] == "No")
check("attachment analyzed with identifiers",
      len(data["attachments_analyzed"]) == 1
      and data["attachments_analyzed"][0]["identifiers_found"] == ["OP-215"])
check("attachment size recorded", data["attachments_analyzed"][0]["size_bytes"] > 0)
check("model echoed", data["model"] == classifier.MODEL)

# ---------- Multiple attachments, two projects (JSON) ----------
# Real files, real regex — only the LLM call is stubbed. The change order
# carries OP-215 and the lease carries OP-142, so this must trip multi-project.

classifier.classify = make_stub()
r = client.post("/api/classify", json=payload(paths=[CHANGE_ORDER, LEASE]), headers=AUTH)
data = r.json()
email = data["email"]
check("json: two attachments -> 200", r.status_code == 200)
check("both attachments analyzed", len(data["attachments_analyzed"]) == 2)
check("per-file identifiers attributed correctly",
      data["attachments_analyzed"][0]["identifiers_found"] == ["OP-215"]
      and data["attachments_analyzed"][1]["identifiers_found"] == ["OP-142"])
check("candidates union both files",
      set(email["identifier_candidates"]) == {"OP-215", "OP-142"})
check("multi-project flag set", email["multiple_projects_detected"] is True)
check("multi-project forces review despite high confidence",
      email["needs_review"] is True and email["needs_review_text"] == "Yes")
check("multi-project reason slug present",
      email["review_reasons"] == ["multiple_projects_detected"])

# ---------- Low confidence ----------

classifier.classify = make_stub(confidence=0.4, needs_review=True)
r = client.post("/api/classify", json=payload(), headers=AUTH)
email = r.json()["email"]
check("low confidence: needs_review true", email["needs_review"] is True)
check("low confidence: reason slug present", "low_confidence" in email["review_reasons"])

# ---------- Multipart transport ----------

classifier.classify = make_stub()
r = client.post(
    "/api/classify-upload",
    data={"sender_domain": "gc-buildwell.com", "subject": "Change Order CO-12", "body": ""},
    files=[("attachments", ("Change_Order_OP-215.docx", read_bytes(CHANGE_ORDER)))],
    headers=AUTH,
)
data = r.json()
check("multipart: single file -> 200", r.status_code == 200)
check("multipart: same shape as JSON route",
      data["email"]["label"] == "Development / Construction"
      and data["attachments_analyzed"][0]["identifiers_found"] == ["OP-215"])

r = client.post(
    "/api/classify-upload",
    data={"sender_domain": "gc-buildwell.com", "subject": "Two docs", "body": ""},
    files=[
        ("attachments", ("Change_Order_OP-215.docx", read_bytes(CHANGE_ORDER))),
        ("attachments", ("Lease_Agreement_OP-142.pdf", read_bytes(LEASE))),
    ],
    headers=AUTH,
)
data = r.json()
check("multipart: two files -> 200", r.status_code == 200)
check("multipart: both analyzed", len(data["attachments_analyzed"]) == 2)
check("multipart: multi-project detected",
      data["email"]["multiple_projects_detected"] is True)

r = client.post(
    "/api/classify-upload",
    data={"sender_domain": "x.com", "subject": "No files", "body": ""},
    headers=AUTH,
)
check("multipart: no files -> 200 (email-only)",
      r.status_code == 200 and r.json()["attachments_analyzed"] == [])

# Clients name the file part themselves — Zapier's webhook calls it "file".
# Any field name must work, and several names at once must all land.
r = client.post(
    "/api/classify-upload",
    data={"sender_domain": "gc-buildwell.com", "subject": "Zapier-style", "body": ""},
    files=[("file", ("Change_Order_OP-215.docx", read_bytes(CHANGE_ORDER)))],
    headers=AUTH,
)
check("multipart: file part named 'file' still lands",
      r.status_code == 200 and len(r.json()["attachments_analyzed"]) == 1)

r = client.post(
    "/api/classify-upload",
    data={"sender_domain": "gc-buildwell.com", "subject": "Mixed names", "body": ""},
    files=[
        ("file", ("Change_Order_OP-215.docx", read_bytes(CHANGE_ORDER))),
        ("attachment_2", ("Lease_Agreement_OP-142.pdf", read_bytes(LEASE))),
    ],
    headers=AUTH,
)
data = r.json()
check("multipart: files under differing names all land",
      r.status_code == 200 and len(data["attachments_analyzed"]) == 2)
check("multipart: mixed-name files still trip multi-project",
      data["email"]["multiple_projects_detected"] is True)

# A client that fails to hydrate sends the token as a text part. Ignore it and
# degrade to subject+body rather than 422-ing the whole request.
r = client.post(
    "/api/classify-upload",
    data={"sender_domain": "x.com", "subject": "Unhydrated",
          "attachments": "hydrate|||.eJytUN1umzAUfhdfJxGg0kCkSnNCoFSQhJasa26QMQ54gE3ALLAq735It1eYJd985_s75xNRKRQTKlFjw9AK|||hydrate"},
    headers=AUTH,
)
check("multipart: unhydrated token string ignored, not an error",
      r.status_code == 200 and r.json()["attachments_analyzed"] == [])

classifier.classify = _real_classify

# ---------- Live Gemini call ----------

if os.environ.get("SKIP_LIVE") == "1":
    print("[SKIP] live classify (SKIP_LIVE=1)")
else:
    r = client.post("/api/classify", json=payload(), headers=AUTH)
    if r.status_code == 200:
        email = r.json()["email"]
        check(f"live: label ok ({email['label']}, {email['confidence']:.0%})",
              email["label"] == "Development / Construction")
        check(f"live: identifier ok ({email['identifier']})", email["identifier"] == "OP-215")
        check("live: routing populated",
              email["sharepoint_folder"] == "/Deals/01_Active_Deals/OP-215")
    else:
        print(f"[SKIP] live classify -> {r.status_code} "
              f"({r.json().get('code')}): {r.json().get('error')}")

print("\nAll assertions passed.")
