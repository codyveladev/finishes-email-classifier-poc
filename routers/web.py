"""HTML form routes: GET / and POST /classify.

Post-Redirect-Get flow uses an in-memory UUID cache so reloads don't re-fire
the classifier — the classifier costs real API quota, so accidental re-submits
would hurt.
"""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import classifier
from attachment_io import temp_file_from_bytes
from cases import CASES
from errors import classifier_exception_to_form_message


router = APIRouter()

templates = Jinja2Templates(directory="templates")
templates.env.cache = None  # workaround: Jinja2 3.1.6 LRU cache trips on Python 3.14 dict-in-tuple key


# One-shot result cache: POST writes, GET reads-and-pops. Prevents reload-resubmit.
_RESULTS: dict[str, dict] = {}


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


@router.get("/", response_class=HTMLResponse)
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


@router.post("/classify", response_class=HTMLResponse)
async def do_classify(
    request: Request,
    sender_domain: str = Form(...),
    subject: str = Form(...),
    body: str = Form(""),
    sample: str = Form(""),
    upload: UploadFile | None = File(None),
):
    result: Optional[dict] = None
    error: Optional[str] = None
    upload_name: Optional[str] = None

    upload_bytes: bytes | None = None
    if upload is not None and upload.filename:
        upload_bytes = await upload.read()
        if upload_bytes:
            upload_name = upload.filename

    # Uploaded file beats the sample dropdown.
    try:
        if upload_bytes:
            with temp_file_from_bytes(upload_bytes, upload_name or "upload.bin") as p:
                result = classifier.classify(sender_domain, subject, body, str(p))
        else:
            attachment_path = sample or None
            result = classifier.classify(sender_domain, subject, body, attachment_path)
    except Exception as e:  # noqa: BLE001 — mapped to a user-facing message
        error = classifier_exception_to_form_message(e)

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
