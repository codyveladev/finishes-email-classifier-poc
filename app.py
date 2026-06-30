"""Phase 3: FastAPI web form. Wraps classifier.classify() — core unchanged."""

import tempfile
import uuid
from pathlib import Path
from dotenv import load_dotenv; load_dotenv()

from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import classifier
from google.genai import errors as genai_errors

# One-shot result cache: POST writes, GET reads-and-pops. Prevents reload-resubmit
# from re-firing the classifier (which would burn free-tier API quota).
_RESULTS: dict[str, dict] = {}

app = FastAPI(title="Attachment Classifier POC")
templates = Jinja2Templates(directory="templates")
templates.env.cache = None  # workaround: Jinja2 3.1.6 LRU cache trips on Python 3.14 dict-in-tuple key

SAMPLES = {
    "— none —": "",
    "Lease (OP-142)": "samples/Lease_Agreement_OP-142.pdf",
    "Vendor Agreement (AS-087)": "samples/Vendor_Agreement_AS-087.pdf",
}

# Mirrors test_cases.py — selecting a preset locks the form to a known-good input.
PRESETS: dict[str, dict] = {
    "Lease — Maple Crossing (OP-142)": {
        "sender_domain": "brightleafretail.com",
        "subject": "Executed lease — Maple Crossing",
        "body": "",
        "sample": "samples/Lease_Agreement_OP-142.pdf",
    },
    "Vendor — Northgate HVAC (AS-087)": {
        "sender_domain": "summitmechanical.com",
        "subject": "HVAC service agreement — Northgate",
        "body": "",
        "sample": "samples/Vendor_Agreement_AS-087.pdf",
    },
    "Invoice #4471 (no attachment)": {
        "sender_domain": "apex-glass.com",
        "subject": "Invoice #4471 due Net 30",
        "body": "",
        "sample": "",
    },
    "Permit approval (no attachment)": {
        "sender_domain": "city-permits.gov",
        "subject": "Permit approval — site grading",
        "body": "",
        "sample": "",
    },
    "Capital call (no attachment)": {
        "sender_domain": "capital-partners.com",
        "subject": "Q3 capital call notice",
        "body": "",
        "sample": "",
    },
    "Change order #12 (no attachment)": {
        "sender_domain": "gc-buildwell.com",
        "subject": "Change order #12 — slab revision",
        "body": "",
        "sample": "",
    },
    "Board minutes (no attachment)": {
        "sender_domain": "admin@ourfirm.com",
        "subject": "Board meeting minutes — March",
        "body": "",
        "sample": "",
    },
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
