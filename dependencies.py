"""FastAPI dependency providers."""

from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import Settings, get_settings
from errors import ApiException


_bearer_scheme = HTTPBearer(auto_error=False, description="API_TOKEN")


def verify_bearer(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Guard for protected routes. Fails closed if API_TOKEN isn't set."""
    if not settings.api_token:
        raise ApiException(
            500, "server_misconfigured",
            "API_TOKEN env var is not set on the server.",
        )
    if creds is None or creds.credentials != settings.api_token:
        raise ApiException(
            401, "unauthorized",
            "Missing or invalid Authorization header (expected 'Bearer <API_TOKEN>').",
        )
