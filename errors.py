"""Error helpers: structured {error, code} responses + Gemini exception translation.

The API contract is {"error": "<message>", "code": "<short_slug>"} with the HTTP
status code carrying the class of failure. This module centralizes that shape
so no route hand-rolls its own error payloads.
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from google.genai import errors as genai_errors


class ApiException(HTTPException):
    """HTTPException whose `detail` is our {error, code} shape.

    Raised from dependencies (auth, validation). A single exception handler on
    the app unwraps it to a flat top-level {error, code} JSON body — matching
    the shape returned directly by route handlers.
    """
    def __init__(self, status_code: int, code: str, msg: str):
        super().__init__(status_code=status_code, detail={"error": msg, "code": code})


def api_error_response(status: int, code: str, msg: str) -> JSONResponse:
    """Build a structured JSON error response from a route handler."""
    return JSONResponse(status_code=status, content={"error": msg, "code": code})


async def api_exception_handler(request: Request, exc: ApiException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.detail)


def classifier_exception_to_api_response(e: Exception) -> JSONResponse:
    """Translate a classifier / Gemini exception into a JSON error response.

    Consumed by the /api/classify route so the mapping lives in one place.
    """
    if isinstance(e, genai_errors.ClientError):
        code = getattr(e, "code", None) or getattr(e, "status_code", None)
        if code == 429:
            return api_error_response(
                429, "rate_limited",
                "Gemini free-tier rate limit hit. Wait ~30s and retry.",
            )
        if code == 403:
            return api_error_response(
                502, "upstream_denied",
                "Gemini API denied the request. Check the server's API key.",
            )
        return api_error_response(502, "upstream_error", f"Gemini API error ({code}): {e}")
    if isinstance(e, genai_errors.ServerError):
        return api_error_response(
            503, "upstream_unavailable",
            f"Gemini upstream is temporarily unavailable: {e}",
        )
    if isinstance(e, genai_errors.APIError):
        return api_error_response(502, "upstream_error", f"Gemini API error: {e}")
    return api_error_response(500, "internal_error", f"{type(e).__name__}: {e}")


def classifier_exception_to_form_message(e: Exception) -> str:
    """Translate a classifier / Gemini exception to a user-facing string for the
    HTML form (not the JSON API)."""
    if isinstance(e, genai_errors.ClientError):
        code = getattr(e, "code", None) or getattr(e, "status_code", None)
        if code == 429:
            return ("Rate limit hit — the Gemini free tier allows 5 requests/minute "
                    "on this model. Wait ~30 seconds and try again.")
        if code == 403:
            return ("Gemini API denied access (403). The API key's Google project "
                    "may not have the Generative Language API enabled, or the key "
                    "is invalid. Generate a fresh key at aistudio.google.com/apikey.")
        return f"Gemini API error ({code}): {e}"
    if isinstance(e, genai_errors.ServerError):
        return f"Gemini server error — try again in a moment. ({e})"
    if isinstance(e, genai_errors.APIError):
        return f"Gemini API error: {e}"
    if isinstance(e, FileNotFoundError):
        return f"Attachment not found: {e}"
    return f"Unexpected error: {type(e).__name__}: {e}"
