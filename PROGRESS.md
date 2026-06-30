# PROGRESS.md — Build Log

Tracking build progress for the Email Attachment Classifier POC (see [PLAN.md](PLAN.md)).

## Phase 1 — Core classifier (CLI) ✅

- [x] Confirm sample PDFs in `samples/`
- [x] Confirm `.env` has `GEMINI_API_KEY`
- [x] Create `requirements.txt`
- [x] Set up venv + install deps
- [x] Smoke test Gemini key
- [x] Build [categories.py](categories.py) — 7 labels + keyword cue map + `keyword_hits()`
- [x] Build [extract.py](extract.py) — `extract_text()` with pdfplumber + pypdf fallback
- [x] Build [classifier.py](classifier.py) — pydantic schema + structured Gemini call
- [x] Build [run_cli.py](run_cli.py) — hard-coded lease case
- [x] **Acceptance:** `python run_cli.py` → "Lease / Occupancy (99%)" with sensible rationale

## Phase 2 — Test it ✅

- [x] Build [test_cases.py](test_cases.py) with all 7 cases from PLAN §8
- [x] Added 13s sleep between cases (free tier: 5 req/min on gemini-2.5-flash)
- [x] **Acceptance: 7/7 correct.** Vendor agreement landed on Vendor Performance (98%) — acceptable per PLAN; rationale is sensible.

## Notes / decisions

- **Model:** `gemini-2.5-flash` (free tier).
- **Skipped OCR** (`pytesseract` / `pdf2image`) — sample PDFs are text-based.
- **Phase 3 (web app) deferred** per user request — core classifier is done.
- **Prompt tightening:** added per-category guidance to [classifier.py](classifier.py) `PROMPT` after a first run misclassified "Permit approval — site grading" as Development/Construction. Explicit rule: a permit *issued by a government office* is Compliance/Legal even if the underlying work is construction. Fixed it.
- **Initial blocker:** first API key was from a denied Google Cloud project (403). User generated a fresh key from AI Studio — that resolved it.
- **Rate limit:** free tier is 5 requests/minute. `test_cases.py` sleeps 13s between cases. If the test set grows, consider caching responses or batching.

## Phase 3 — Web form front end ✅

- [x] Add `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart` to requirements
- [x] Build [app.py](app.py) — FastAPI app wrapping `classifier.classify()`; core unchanged
- [x] Build [templates/form.html](templates/form.html) — styled form with sender/subject/body, sample dropdown, **and file upload**
- [x] File upload: uploaded PDF saved to a temp file, classified, then cleaned up. Upload takes priority over the sample dropdown.
- [x] Single attachment per request (multi-attachment is queued as Phase 5 in PLAN)
- [x] App imports and exposes `/` (form) and `/classify` (POST) routes
- [x] **Acceptance:** run `.venv/Scripts/uvicorn app:app --reload` and open http://127.0.0.1:8000

## Phase 3 fixes (Python 3.14 compatibility) ✅

- [x] Jinja2 3.1.6 LRU cache crashes on Python 3.14 (`tuple` key contains `dict`). Workaround: `templates.env.cache = None`.
- [x] Starlette changed `TemplateResponse` signature to `TemplateResponse(request, name, context)`. Updated both routes.

## Phase 6 — Project / Deal / Asset identifier extraction ✅

- [x] Added `find_identifiers()` regex pre-pass for `OP-####` (Deal) and `AS-###` (Asset) in [classifier.py](classifier.py)
- [x] Extended `Classification` pydantic schema with `identifier` (nullable) and `identifier_rationale`
- [x] Updated prompt with identifier scheme + selection guidance (subject > body > attachment)
- [x] `build_signal()` emits `IDENTIFIER CANDIDATES:` line
- [x] [run_cli.py](run_cli.py) prints identifier + rationale + candidates
- [x] [templates/form.html](templates/form.html) shows identifier with Deal/Asset label and the rationale
- [x] **Acceptance:** lease PDF case extracts `OP-142` as Deal with sensible rationale ("explicitly stated as the 'Project Reference' within the attached Commercial Lease Agreement")

## Phase 3 polish (post-MVP) ✅

- [x] **Branded header** — "Finishes Solutions Email Classifier POC" + live `model: <id>` badge pulled from `classifier.MODEL`
- [x] **Preset test cases** — dropdown of all 7 cases from `test_cases.py`; selecting one populates fields and locks them (readonly inputs + disabled select with mirrored hidden input)
- [x] **Clear link** next to Classify — navigates to `/`
- [x] **Post-Redirect-Get** — POST `/classify` stashes result in an in-memory UUID cache and returns 303 → `/?rid=<uuid>`. GET pops the cache (one-shot). Reload no longer re-fires the API.
- [x] **Graceful API error handling** — `/classify` catches `google.genai.errors.ClientError` (429, 403, etc.), `ServerError`, generic `APIError`, `FileNotFoundError`, and bare `Exception`. Errors render in a red error block instead of crashing with a 500.
- [x] Model switched to `gemini-2.5-flash-lite` (cheaper / higher free-tier quota for iteration)

## Cleanup pass ✅

- [x] Deleted `smoke_test.py` (one-off, served its purpose)
- [x] Added [cases.py](cases.py) — single source of truth for the 7 test cases (frozen `Case` dataclass)
- [x] [app.py](app.py) builds `PRESETS` from `cases.CASES`
- [x] [test_cases.py](test_cases.py) imports `cases.CASES`; runs **one case by default** to conserve free-tier quota — set `RUN_ALL=1` to run all 7 with the 13s/req delay

## Future plans added to PLAN.md

- **Phase 4** ([PLAN.md §11](PLAN.md)) — Word + Excel attachment support
- **Phase 5** ([PLAN.md §12](PLAN.md)) — Multiple attachments per email

## Next steps (deferred / out of scope)

- Real email ingestion (Gmail/IMAP), Monday.com / SharePoint writes.
- Confidence calibration; deterministic keyword-vs-LLM tie-breaker.
