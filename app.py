"""FastAPI app entry point. Wires routers and the shared exception handler.

Route logic lives in routers/. Shared helpers live in config.py, dependencies.py,
errors.py, and attachment_io.py. This file stays intentionally small so it
reads at a glance.
"""

from dotenv import load_dotenv; load_dotenv()

from fastapi import FastAPI

from errors import ApiException, api_exception_handler
from routers import api as api_router
from routers import web as web_router


app = FastAPI(title="Finishes Solutions Email Classifier")

# Unwrap ApiException.detail so error responses stay {error, code} flat.
app.add_exception_handler(ApiException, api_exception_handler)

app.include_router(web_router.router)
app.include_router(api_router.router, prefix="/api")
