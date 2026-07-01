"""Phase 3: FastAPI web form. Phase 7: JSON webhook API alongside.
Both wrap classifier.classify() — core unchanged."""

import base64
import os
import tempfile
import uuid
from pathlib import Path
from dotenv import load_dotenv; load_dotenv()

from fastapi import FastAPI, Form, Request, UploadFile, File, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import classifier
import routing
from cases import CASES
from schemas import (
    ApiError, AttachmentResult, ClassifyRequest, ClassifyResponse,
    EmailContext, RoutingHints, Summary,
)
from google.genai import errors as genai_errors

API_TOKEN = os.environ.get("API_TOKEN")  # None → endpoint fails closed
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024   # 10 MB soft cap per file

# One-shot result cache: POST writes, GET reads-and-pops. Prevents reload-resubmit
# from re-firing the classifier (which would burn free-tier API quota).
_RESULTS: dict[str, dict] = {}

app = FastAPI(title="Attachment Classifier POC")
templates = Jinja2Templates(directory="templates")
templates.env.cache = None  # workaround: Jinja2 3.1.6 LRU cache trips on Python 3.14 dict-in-tuple key

SAMPLES = {
    "— none —": "",
    "Lease (OP-142) — PDF": "samples/Lease_Agreement_OP-142.pdf",
    "Vendor Agreement (AS-087) — PDF": "samples/Vendor_Agreement_AS-087.pdf",
    "Change Order (OP-215) — Word": "samples/Change_Order_OP-215.docx",
}

# Presets built from the shared CASES list — single source of truth shared with test_cases.py.
PRESETS: dict[str, dict] = {
    c.name: {
        "sender_domain": c.sender_domain,
        "subject": c.subject,
        "body": c.body,
        "sample": c.attachment,
    }
    for c in CASES
}


@app.get("/", response_class=HTMLResponse)
def form(request: Request, rid: str | None = None):
    cached = _RESULTS.pop(rid, None) if rid else None
    ctx = {
        "samples": SAMPLES,
        "presets": PRESETS,
        "result": None,
        "model": classifier.MODEL,
    }
    if cached:
        ctx.update(cached)
    return templates.TemplateResponse(request, "form.html", ctx)


@app.post("/classify", response_class=HTMLResponse)
async def do_classify(
    request: Request,
    sender_domain: str = Form(...),
    subject: str = Form(...),
    body: str = Form(""),
    sample: str = Form(""),
    upload: UploadFile | None = File(None),
):
    # Uploaded file beats sample dropdown.
    attachment_path: str | None = None
    tmp_path: Path | None = None
    upload_name: str | None = None

    if upload is not None and upload.filename:
        data = await upload.read()
        if data:
            suffix = Path(upload.filename).suffix or ".bin"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(data)
            tmp.close()
            tmp_path = Path(tmp.name)
            attachment_path = str(tmp_path)
            upload_name = upload.filename
    if attachment_path is None and sample:
        attachment_path = sample

    result: dict | None = None
    error: str | None = None
    try:
        result = classifier.classify(sender_domain, subject, body, attachment_path)
    except genai_errors.ClientError as e:
        code = getattr(e, "code", None) or getattr(e, "status_code", None)
        if code == 429:
            error = ("Rate limit hit — the Gemini free tier allows 5 requests/minute "
                     "on this model. Wait ~30 seconds and try again.")
        elif code == 403:
            error = ("Gemini API denied access (403). The API key's Google project "
                     "may not have the Generative Language API enabled, or the key "
                     "is invalid. Generate a fresh key at aistudio.google.com/apikey.")
        else:
            error = f"Gemini API error ({code}): {e}"
    except genai_errors.ServerError as e:
        error = f"Gemini server error — try again in a moment. ({e})"
    except genai_errors.APIError as e:
        error = f"Gemini API error: {e}"
    except FileNotFoundError as e:
        error = f"Attachment not found: {e}"
    except Exception as e:
        error = f"Unexpected error: {type(e).__name__}: {e}"
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    rid = uuid.uuid4().hex
    _RESULTS[rid] = {
        "result": result,
        "error": error,
        "sender_domain": sender_domain,
        "subject": subject,
        "body": body,
        "selected_sample": sample,
        "upload_name": upload_name,
    }
    # 303 forces the browser to GET; reloading the GET is harmless (cache already popped).
    return RedirectResponse(url=f"/?rid={rid}", status_code=303)


# ---------- Phase 7: JSON webhook API ----------

def _api_err(status: int, code: str, msg: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": msg, "code": code})


@app.post("/api/classify")
def api_classify(
    payload: ClassifyRequest,
    authorization: str | None = Header(default=None),
):
    # Auth — fail closed if the token is not configured or does not match.
    if not API_TOKEN:
        return _api_err(500, "server_misconfigured",
                        "API_TOKEN env var is not set on the server.")
    if authorization != f"Bearer {API_TOKEN}":
        return _api_err(401, "unauthorized",
                        "Missing or invalid Authorization header (expected 'Bearer <API_TOKEN>').")

    if not payload.attachments:
        return _api_err(400, "no_attachments",
                        "attachments must contain at least one file "
                        "(zero-attachment classification is not yet supported).")
    if len(payload.attachments) > 1:
        return _api_err(400, "multi_attachment_unsupported",
                        "Phase 7 caps attachments at 1. Multi-attachment is Phase 5.")

    att_in = payload.attachments[0]

    try:
        data = base64.b64decode(att_in.content_base64, validate=True)
    except Exception:
        return _api_err(400, "invalid_base64",
                        f"attachments[0].content_base64 could not be decoded for '{att_in.filename}'.")

    if len(data) > MAX_ATTACHMENT_BYTES:
        return _api_err(413, "attachment_too_large",
                        f"'{att_in.filename}' is {len(data)} bytes; the limit is {MAX_ATTACHMENT_BYTES}.")

    suffix = Path(att_in.filename).suffix or ".bin"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    tmp_path = Path(tmp.name)

    try:
        result = classifier.classify(
            payload.sender_domain, payload.subject, payload.body, str(tmp_path),
        )
    except genai_errors.ClientError as e:
        code = getattr(e, "code", None) or getattr(e, "status_code", None)
        if code == 429:
            return _api_err(429, "rate_limited",
                            "Gemini free-tier rate limit hit. Wait ~30s and retry.")
        if code == 403:
            return _api_err(502, "upstream_denied",
                            "Gemini API denied the request. Check the server's API key.")
        return _api_err(502, "upstream_error", f"Gemini API error ({code}): {e}")
    except genai_errors.ServerError as e:
        return _api_err(503, "upstream_unavailable",
                        f"Gemini upstream is temporarily unavailable: {e}")
    except genai_errors.APIError as e:
        return _api_err(502, "upstream_error", f"Gemini API error: {e}")
    except Exception as e:
        return _api_err(500, "internal_error",
                        f"{type(e).__name__}: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)

    # Layer routing hints onto the classifier result.
    hints = routing.compute_routing(
        label=result["label"],
        identifier=result["identifier"],
        keyword_hits=result["keyword_hits"],
        sender_domain=payload.sender_domain,
    )

    att_result = AttachmentResult(
        filename=att_in.filename,
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

    response = ClassifyResponse(
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
    return response
