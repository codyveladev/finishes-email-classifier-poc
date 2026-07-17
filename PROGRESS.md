# PROGRESS.md — Build Log

Tracking build progress for the Email Attachment Classifier POC (see [PLAN.md](PLAN.md)).

## Current status

**The full pipeline runs end to end against a real mailbox.** Outlook → Power
Automate → SharePoint → this classifier → Zapier → Monday intake board.
See **[INTEGRATION.md](INTEGRATION.md)** for how it's wired, the exact
expressions, and the traps.

Verified: an email with three PDFs (`OP-118`, `OP-142`, `AS-087`) files all
three to SharePoint, extracts text from inside each one, unions the identifiers,
trips `multiple_projects_detected`, and lands a flagged item on the board.

- All classifier phases shipped: CLI, test suite, web form, identifier
  extraction, Word/.docx, JSON + multipart API, multi-attachment.
- Model: `gemini-2.5-flash`.
- Deployed on Render (build: `pip install -r requirements.txt`; start:
  `uvicorn app:app --host 0.0.0.0 --port $PORT`; env: `GEMINI_API_KEY`,
  `API_TOKEN`, `PYTHON_VERSION=3.12.6`).
- Known gaps and next steps: [INTEGRATION.md §7](INTEGRATION.md).

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

## Docs alignment pass ✅

- [x] Rewrote PLAN.md status snapshot at the top of the file
- [x] Marked shipped phases as ✅ with pointers to the actual files
- [x] Updated project structure to match the current tree (includes `cases.py`, `PROGRESS.md`, no `smoke_test.py`)
- [x] Fixed the model note (now `gemini-2.5-flash-lite`)
- [x] Split Phase 4 into 4a (Word/docx — next) and 4b (Excel/xlsx — deferred)
- [x] Checked off the Definition of Done in PLAN §10

## Phase 4a — Word (`.docx`) attachment support ✅

- [x] Added `python-docx` to `requirements.txt` (v1.2.0)
- [x] Added sample `samples/Change_Order_OP-215.docx` (Development/Construction category, prose paragraphs + line-items table, `OP-215` identifier)
- [x] Refactored [extract.py](extract.py) into `extract_text()` dispatcher + `_extract_pdf` + `_extract_docx`; unknown extensions return `""`
- [x] `_extract_docx` iterates both `doc.paragraphs` and `doc.tables` (rows joined with tabs)
- [x] Added 50k-char per-file soft cap (`MAX_CHARS_PER_FILE`) before the 6000-char `build_signal()` truncation
- [x] Added case to [cases.py](cases.py) — "Change Order — Riverbend Commons (OP-215, .docx)" → `Development / Construction`
- [x] Added the docx to the web form's `SAMPLES` dropdown and extended the file-upload `accept` attribute
- [x] **Acceptance:** end-to-end classify of the new docx case → `Development / Construction` @ 100%, identifier `OP-215` extracted correctly, rationale references construction indicators from both paragraph text (RFIs, submittals) and table contents.

### Notes

- Verified during testing: extractor pulls both paragraph text *and* table content. A paragraphs-only extractor would silently lose the cost breakdown table — worth remembering for future formats.
- `gemini-2.5-flash-lite` returned a 503 UNAVAILABLE during initial testing (upstream Gemini demand spike). Switched to `gemini-2.5-flash` briefly to verify the classify path; not making that the default since it has lower free-tier quota. The web app's existing error handler already covers 503s gracefully.
- Legacy `.doc` and Excel `.xlsx` remain out of scope for this phase (see [PLAN.md §11, §12](PLAN.md)).

## Phase 7 — JSON webhook API + routing hints ✅

- [x] [routing.py](routing.py) — pure functions mapping `(label, identifier, keyword_hits, sender_domain)` → SharePoint folder + Monday board/group + priority hint. No external calls; illustrative board names ready to be replaced with real workspace names.
- [x] [schemas.py](schemas.py) — pydantic `AttachmentIn`, `ClassifyRequest`, `AttachmentResult`, `RoutingHints`, `EmailContext`, `Summary`, `ClassifyResponse`, `ApiError`.
- [x] `POST /api/classify` in [app.py](app.py) — bearer auth, base64 decode, 10 MB per-file cap, temp-file lifecycle, calls `classifier.classify()`, layers routing hints, builds summary.
- [x] `API_TOKEN` env var; endpoint fails closed with 500 if unset, 401 if wrong.
- [x] Graceful error mapping: 429 rate limit → 429, 403 upstream → 502, 503 upstream → 503, other Gemini errors → 502, unknown exceptions → 500. Structured `{ "error", "code" }` bodies.
- [x] Zero-attachment support: empty `attachments` array classifies subject + body only, mirroring the web form's "— none —" option. Response uses `"(email body)"` as the sentinel filename so downstream consumers read from `attachments[0]` uniformly.
- [x] [test_api.py](test_api.py) — 18 assertions covering auth, validation, error paths, stubbed happy path, and a live Gemini smoke call. Set `SKIP_LIVE=1` to skip the live call.
- [x] [.env.example](.env.example) — documents `GEMINI_API_KEY` + `API_TOKEN`.
- [ ] Set `API_TOKEN` env var on Render before merging (paste any long random string).

### Curl example

```bash
# Base64-encode a sample once
B64=$(base64 -w0 samples/Change_Order_OP-215.docx)

curl -X POST http://127.0.0.1:8000/api/classify \
  -H "Authorization: Bearer <your API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{
    \"sender_domain\": \"gc-buildwell.com\",
    \"subject\": \"Change Order CO-12 — Riverbend Commons\",
    \"body\": \"\",
    \"attachments\": [
      {\"filename\": \"Change_Order_OP-215.docx\", \"content_base64\": \"$B64\"}
    ]
  }"
```

Response shape and routing hint contract are documented in [PLAN.md §15](PLAN.md).

## Refactor pass ✅ — FastAPI structure

`app.py` had grown to ~250 lines with three concerns tangled (form, API, PRG cache, exception mapping, config). Split into focused modules following FastAPI best practices:

- [x] [config.py](config.py) — `Settings` model + cached `get_settings()`; all env reads in one place.
- [x] [dependencies.py](dependencies.py) — `verify_bearer` using `HTTPBearer` scheme (also gives `/docs` an Authorize button).
- [x] [errors.py](errors.py) — `ApiException` + `api_exception_handler` + Gemini-exception translators for both API and form paths.
- [x] [attachment_io.py](attachment_io.py) — `temp_file_from_bytes()` context manager, reused by both routes.
- [x] [routers/web.py](routers/web.py) — form GET/POST + PRG cache + `SAMPLES` + `PRESETS`.
- [x] [routers/api.py](routers/api.py) — JSON endpoint, protected by `Depends(verify_bearer)`; router-level dependency means auth is one line to add to future protected endpoints.
- [x] [app.py](app.py) — down to 23 lines. Just: load env, create `FastAPI()`, register exception handler, include routers.
- [x] `test_api.py` — updated `app.classifier.*` monkey-patch targets to patch `classifier.*` directly (same module object, cleaner import path).
- [x] **Acceptance:** 20/20 API tests pass, web form still renders correctly with model badge + presets.

No behavior change — pure structural refactor.

## Response shape v2 ✅ — email-level classification

The v1 API response classified "per attachment," which implied N labels per
email. Wrong model: downstream creates **one intake item per email**, so the
email is the unit of classification. Attachments are evidence, not outputs.

- [x] [schemas.py](schemas.py) — `EmailResult` carries label, confidence, identifier, keyword hits, and all routing hints flat at email level. `AttachmentAnalyzed` is a slim audit record (filename, size, `identifiers_found`) with no label/confidence. Dropped the `summary` block and nested `routing` object entirely.
- [x] [routers/api.py](routers/api.py) — extracts attachment text in the router (single extraction, reused for both the per-file identifier scan and the classify call via the new `attachment_text` parameter on `classifier.classify()`).
- [x] **Multi-project detection** — `email.multiple_projects_detected` is true when >1 distinct identifier appears across subject + body + attachments. Forces `needs_review = true` even at high confidence, since splitting an intake item is a human decision.
- [x] **`review_reasons`** — stable machine-readable slugs (`low_confidence`, `multiple_projects_detected`) so orchestrators can branch on *why* something needs review, and the triage board can show the reason.
- [x] [classifier.py](classifier.py) — `classify()` / `build_signal()` accept optional pre-extracted `attachment_text`; path-based callers (web form, CLI, test_cases) unchanged.
- [x] [test_api.py](test_api.py) — rewritten for the new shape: 27 assertions including multi-project and low-confidence stub cases. All passing, live call included.

**Breaking change for Zapier/Power Automate mappings:** field paths moved from
`attachments[0].label` / `attachments[0].routing.*` to `email.label` /
`email.*`. Update any existing Zap field mappings after merging.

## Phase 5 — Multiple attachments + multipart transport ✅

Driven by the Outlook trigger: real emails carry several attachments, and
Zapier only hydrates file fields natively in form-data payloads. Both problems,
one piece of work.

- [x] [service.py](service.py) — new module holding the transport-agnostic pipeline. Both routes normalize to `IncomingFile(filename, data)` and call `run_classification()`.
- [x] [routers/api.py](routers/api.py) — `POST /api/classify` (JSON+base64) cap lifted; new `POST /api/classify-upload` (multipart) for Zapier. Both thin; validation shared.
- [x] **Even budget split** — each attachment gets `ATTACHMENT_TEXT_BUDGET // N` prompt chars in a `--- ATTACHMENT: {filename} ---` block, so one long file can't crowd the others out.
- [x] **Full-text identifier scan** — per-file regex runs on complete extracted text, not the trimmed prompt text. New `identifier_candidates` param on `classify()` carries the complete union through, so a code buried deep in a long doc still reaches the reviewer.
- [x] **Attachment cap** — `MAX_ATTACHMENTS` (default 10) → `400 too_many_attachments`. Guards the fan-out cost risk.
- [x] [test_api.py](test_api.py) — 36 stubbed assertions + live call. Multi-project case uses both real samples (change order `OP-215` + lease `OP-142`) with only the LLM stubbed, so the regex/attribution logic is genuinely exercised.
- [x] **Acceptance:** two-file email correctly attributes `OP-215` to the change order and `OP-142` to the lease, unions both into candidates, trips `multiple_projects_detected`, and forces `needs_review` despite 98% confidence. Multipart route returns an identical shape to JSON. CLI and web form unaffected.

### For the Zapier Outlook flow

The Code step, hydrate-URL fetch, and base64 encoding all go away. Use
**Webhooks by Zapier → POST**, Payload Type **`form`**, URL
`/api/classify-upload`, and map the Outlook attachment field directly into an
`attachments` key. Zapier hydrates the files and streams them as real multipart
parts. Bearer header unchanged.

## Deferred / out of scope for the POC

- Phase 4b — Excel (`.xlsx`) via `openpyxl`
- Real email ingestion (Exchange/Graph/IMAP), Monday.com / SharePoint writes (both live upstream/downstream of this service — see PLAN.md discussion)
- Confidence calibration; deterministic keyword-vs-LLM tie-breaker
- Idempotency / dedup (defer until real orchestrator produces observable duplicates)
