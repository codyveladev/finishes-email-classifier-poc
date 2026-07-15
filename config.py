"""Central config. Environment vars read once via get_settings() (cached)."""

import os
from functools import lru_cache
from pydantic import BaseModel


class Settings(BaseModel):
    api_token: str | None
    max_attachment_bytes: int
    max_attachments: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        api_token=os.environ.get("API_TOKEN"),
        max_attachment_bytes=int(
            os.environ.get("MAX_ATTACHMENT_BYTES", 10 * 1024 * 1024)
        ),
        # Caps LLM cost per email: a reply-all thread with 40 attachments
        # should be rejected loudly, not classified quietly.
        max_attachments=int(os.environ.get("MAX_ATTACHMENTS", 10)),
    )
