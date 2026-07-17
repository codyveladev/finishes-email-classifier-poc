"""JSON and multipart webhook endpoints.

Two transports, one pipeline:

- POST /api/classify         JSON body, attachments base64-encoded.
                             For Power Automate, curl, anything that can build JSON.
- POST /api/classify-upload  multipart/form-data, attachments as real file parts
                             under any field name. For Zapier, whose webhook
                             only hydrates files via its own "File" field, and
                             names the resulting part on its terms, not ours.

Both normalize to service.IncomingFile and hand off to run_classification().
"""

import base64
import binascii
import json
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

import service
from config import Settings, get_settings
from dependencies import verify_bearer
from errors import api_error_response, classifier_exception_to_api_response
from schemas import ClassifyRequest, ClassifyResponse
from service import IncomingFile


router = APIRouter(
    tags=["classifier"],
    dependencies=[Depends(verify_bearer)],
)


_DATA_URI_PREFIX = re.compile(r"^data:[^;,]*;base64,", re.IGNORECASE)


def decode_attachment_base64(raw: str) -> bytes:
    """Decode base64 from an orchestrator we don't control.

    Strict decoding rejects anything that isn't pure base64, which fails on
    input that is otherwise perfectly good. Three real-world shapes we accept:

    - Logic Apps / Power Automate binary envelope:
      {"$content-type": "application/pdf", "$content": "JVBERi0x..."}
    - data URIs: "data:application/pdf;base64,JVBERi0x..."
    - base64 line-wrapped at 76 chars, which many encoders do by default

    Raises binascii.Error if it still isn't base64 after unwrapping.
    """
    text = raw.strip()

    # Power Automate hands binary fields over in an envelope when a flow
    # string-interpolates them; the payload lives under "$content".
    if text.startswith("{"):
        try:
            envelope = json.loads(text)
        except ValueError:
            pass
        else:
            if isinstance(envelope, dict) and "$content" in envelope:
                text = str(envelope["$content"]).strip()

    text = _DATA_URI_PREFIX.sub("", text)
    # Drop whitespace/newlines rather than rejecting the payload over them.
    text = re.sub(r"\s+", "", text)

    # Re-pad: some encoders strip the trailing '=' characters.
    remainder = len(text) % 4
    if remainder:
        text += "=" * (4 - remainder)

    # Validate strictly now that the wrapping is off. Without this, b64decode
    # silently discards characters outside the alphabet, so genuine garbage
    # would decode to garbage bytes — and the classifier would read nothing
    # from the "attachment" and quietly fall back to subject+body.
    return base64.b64decode(text, validate=True)


def _validate_files(files: list[IncomingFile], settings: Settings) -> JSONResponse | None:
    """Return an error response if the batch is unusable, else None."""
    if len(files) > settings.max_attachments:
        return api_error_response(
            400, "too_many_attachments",
            f"{len(files)} attachments exceeds the limit of {settings.max_attachments}.",
        )
    for f in files:
        if len(f.data) > settings.max_attachment_bytes:
            return api_error_response(
                413, "attachment_too_large",
                f"'{f.filename}' is {len(f.data)} bytes; "
                f"the limit is {settings.max_attachment_bytes}.",
            )
    return None


def _run(sender_domain: str, subject: str, body: str,
         files: list[IncomingFile], settings: Settings) -> ClassifyResponse | JSONResponse:
    invalid = _validate_files(files, settings)
    if invalid is not None:
        return invalid
    try:
        return service.run_classification(sender_domain, subject, body, files)
    except Exception as e:  # noqa: BLE001 — every failure type maps to a structured error
        return classifier_exception_to_api_response(e)


@router.post("/classify", response_model=ClassifyResponse)
def classify_json(
    payload: ClassifyRequest,
    settings: Settings = Depends(get_settings),
) -> ClassifyResponse | JSONResponse:
    files: list[IncomingFile] = []
    for i, att in enumerate(payload.attachments):
        try:
            data = decode_attachment_base64(att.content_base64)
        except (binascii.Error, ValueError):
            preview = att.content_base64[:60]
            return api_error_response(
                400, "invalid_base64",
                f"attachments[{i}].content_base64 could not be decoded for "
                f"'{att.filename}'. Received {len(att.content_base64)} chars "
                f"starting with: {preview!r}",
            )
        files.append(IncomingFile(filename=att.filename, data=data))

    return _run(payload.sender_domain, payload.subject, payload.body, files, settings)


@router.post("/classify-upload", response_model=ClassifyResponse)
async def classify_upload(
    request: Request,
    sender_domain: str = Form(...),
    subject: str = Form(...),
    body: str = Form(""),
    settings: Settings = Depends(get_settings),
) -> ClassifyResponse | JSONResponse:
    # Take file parts under ANY field name rather than a declared `attachments`
    # param. Clients name the part after their own field, not ours — Zapier's
    # webhook calls it "file", Power Automate lets you pick, curl uses whatever
    # -F says. Non-file parts (including Zapier's unhydrated token strings) are
    # ignored rather than erroring, so a misconfigured mapping degrades to a
    # subject+body classification instead of a 422.
    form = await request.form()
    files: list[IncomingFile] = []
    for _, value in form.multi_items():
        if not isinstance(value, StarletteUploadFile) or not value.filename:
            continue
        data = await value.read()
        if data:
            files.append(IncomingFile(filename=value.filename, data=data))

    return _run(sender_domain, subject, body, files, settings)
