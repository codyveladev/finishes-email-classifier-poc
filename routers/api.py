"""JSON and multipart webhook endpoints.

Two transports, one pipeline:

- POST /api/classify         JSON body, attachments base64-encoded.
                             For Power Automate, curl, anything that can build JSON.
- POST /api/classify-upload  multipart/form-data, attachments as real file parts.
                             For Zapier, which hydrates file fields natively in
                             form payloads but degrades them to URLs in JSON.

Both normalize to service.IncomingFile and hand off to run_classification().
"""

import base64

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

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
            data = base64.b64decode(att.content_base64, validate=True)
        except Exception:
            return api_error_response(
                400, "invalid_base64",
                f"attachments[{i}].content_base64 could not be decoded "
                f"for '{att.filename}'.",
            )
        files.append(IncomingFile(filename=att.filename, data=data))

    return _run(payload.sender_domain, payload.subject, payload.body, files, settings)


@router.post("/classify-upload", response_model=ClassifyResponse)
async def classify_upload(
    sender_domain: str = Form(...),
    subject: str = Form(...),
    body: str = Form(""),
    attachments: list[UploadFile] = File(default=[]),
    settings: Settings = Depends(get_settings),
) -> ClassifyResponse | JSONResponse:
    files: list[IncomingFile] = []
    for upload in attachments:
        # Zapier sends an empty part when a file field maps to nothing; skip
        # those rather than classifying a zero-byte "attachment".
        if not upload.filename:
            continue
        data = await upload.read()
        if data:
            files.append(IncomingFile(filename=upload.filename, data=data))

    return _run(sender_domain, subject, body, files, settings)
