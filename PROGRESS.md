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

## Next steps (deferred / out of scope)

- Phase 3: FastAPI form front end ([PLAN.md §9](PLAN.md)).
- Real email ingestion (Gmail/IMAP), file upload, Monday.com / SharePoint writes.
- Confidence calibration; deterministic keyword-vs-LLM tie-breaker.
