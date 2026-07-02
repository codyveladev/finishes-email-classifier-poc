# PLAN.md — Email Attachment Classifier (Proof of Concept)

> Detailed build history lives in [PROGRESS.md](PROGRESS.md). This doc is the plan and the current status.

## Status snapshot

| Phase | Status | What it delivers |
|---|---|---|
| 1 — Core classifier (CLI) | ✅ shipped | `classifier.py` + `run_cli.py`; keyword pre-pass + Gemini structured call |
| 2 — Test suite | ✅ shipped | `test_cases.py` runs 1 case by default (`RUN_ALL=1` runs all 7); shared `cases.py` |
| 3 — Web form (FastAPI) | ✅ shipped | `app.py` + upload, presets, Clear, PRG, graceful error handling, model badge |
| 6 — Identifier extraction (OP-####/AS-###) | ✅ shipped | regex pre-pass + LLM picks best candidate + rationale |
| 4a — Word (.docx) attachments | ✅ shipped | dispatch on extension inside `extract.py`; `python-docx` iterates paragraphs + tables |
| **7 — JSON webhook API + routing hints** | 🔜 **next** | `POST /api/classify` with bearer auth; base64 attachments; response includes SharePoint folder + Monday board hints so Zapier/Power Automate can drive the intake flow |
| 4b — Excel (.xlsx) attachments | 📋 deferred | `openpyxl` sheet-flattening; sample xlsx + test case |
| 5 — Multiple attachments per email | 📋 deferred | request/response shapes already list-based; just lift the current 1-attachment cap |

**Model in use:** `gemini-2.5-flash-lite` (free tier, higher quota than 2.5-flash for iteration).

---

## 1. Goal

Build a small, self-contained classifier that takes the signals of an incoming
email and returns **one category label plus a confidence score**. This POC
proves the *classification brain* only — it does **not** connect to a real
mailbox, SharePoint, or Monday.com yet. Those come later.

**Input signals**

- `sender_domain` — e.g. `brightleafretail.com`
- `subject` — the email subject line
- keyword scan — keywords detected across subject + body + attachment text
- `attachment_path` — **hard-coded local file path for now** (one PDF)

**Output** (current shape, includes identifier extraction shipped in Phase 6)

```json
{
  "label": "Lease / Occupancy",
  "confidence": 0.90,
  "rationale": "...",
  "identifier": "OP-142",
  "identifier_rationale": "Explicitly stated as the 'Project Reference' in the attached lease.",
  "identifier_candidates": ["OP-142"],
  "method": "gemini",
  "keyword_hits": ["lease", "tenant", "premises"],
  "needs_review": false
}
```

The AI classifier is **Google Gemini** (free tier via Google AI Studio),
chosen for its free quota during the POC.

---

## 2. Categories

Classify into exactly one of these seven. The keyword cues feed a cheap
deterministic pre-pass; Gemini makes the final call (it handles overlap and
ambiguity the keywords can't).

| # | Label | Keyword cues (non-exhaustive) |
|---|-------|-------------------------------|
| 1 | Development / Construction | change order, RFI, submittal, punch list, contractor, drawings, mobilization, site work |
| 2 | Payment / Billing | invoice, pay application, remittance, statement, past due, billing, receipt, wire |
| 3 | Lease / Occupancy | lease, tenant, landlord, premises, rent, occupancy, estoppel, CAM, renewal, vacancy |
| 4 | Compliance / Legal | permit, license, compliance, violation, zoning, attorney, litigation, NDA, certificate of insurance |
| 5 | Capital / Finance | capital call, equity, loan, debt, refinance, draw, budget, pro forma, distribution, investor |
| 6 | Vendor Performance | vendor, supplier, service agreement, SLA, scope of work, maintenance, work order, KPI |
| 7 | General Governance | minutes, board, policy, memo, approval, resolution, correspondence (default / catch-all) |

> **Deliberate overlaps exist** (e.g. "permit" cues both #1 and #4; "agreement"
> cues both #4 and #6). That's realistic. The keyword pass only *proposes*
> candidates — the LLM resolves the overlap. The vendor agreement test file
> below is intentionally ambiguous between **Vendor Performance** and
> **Compliance / Legal**, which makes it a good calibration case.

---

## 3. How classification works

```
inputs ──► assemble signal ──► keyword + identifier pre-pass ──► Gemini (structured) ──► result
           (domain+subject+     (cheap candidates:              (label + confidence +
            body+attachment)     hits[], ids[])                  identifier + rationales)
```

1. **Assemble signal text** — concatenate sender domain, subject, body, and the
   extracted attachment text into one block.
2. **Keyword pre-pass** — scan the block against the cue lists; record hits.
3. **Identifier pre-pass** — regex the block for `OP-####` (Deal) and `AS-###`
   (Asset) codes; collect deduped candidates.
4. **Gemini call** — send the signal text (with keyword hits and identifier
   candidates included) plus a constrained schema; the model returns the label,
   confidence (0–1), rationale, the picked identifier, and identifier rationale.
5. **Combine & emit** — return the payload. If confidence is below the
   threshold (`0.60`), flag `needs_review` instead of trusting the label.

> ⚠️ **Confidence is self-reported by the model and is not calibrated.** Treat it
> as a rough signal for triage, not a probability. The threshold is a product
> decision, not a statistical one.

---

## 4. Tech & prerequisites

- Python 3.11+
- `google-genai` (the current unified SDK), `pydantic`
- `pdfplumber` + `pypdf` for attachment text; optional `pytesseract` + `pdf2image` for scanned PDFs
- `python-dotenv` for the API key
- Phase 3 web app: `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`
- A **Gemini API key** from [Google AI Studio](https://aistudio.google.com/) (free tier)

`requirements.txt`

```
google-genai
pydantic
pdfplumber
pypdf
python-dotenv
fastapi
uvicorn[standard]
jinja2
python-multipart        # required for FastAPI form posts
# optional OCR:
# pytesseract
# pdf2image
```

---

## 5. Project structure (as-shipped)

```
finishes-email-classifier-poc/
├── .env                  # GEMINI_API_KEY=... (gitignored)
├── .gitignore
├── requirements.txt
├── PLAN.md               # this doc
├── PROGRESS.md           # build log
├── categories.py         # 7 labels + keyword cue map + keyword_hits()
├── extract.py            # attachment path -> text (PDF via pdfplumber → pypdf)
├── classifier.py         # keyword + identifier pre-pass + Gemini call — THE CORE
├── cases.py              # shared Case dataclass; single source of test cases
├── run_cli.py            # Phase 1 CLI demo (hard-coded lease case)
├── test_cases.py         # Phase 2 test runner (1 case by default; RUN_ALL=1 for all)
├── app.py                # Phase 3 FastAPI form
├── templates/
│   └── form.html         # styled form with presets, upload, PRG, error block
└── samples/
    ├── Lease_Agreement_OP-142.pdf
    └── Vendor_Agreement_AS-087.pdf
```

---

## 6. Setup

```bash
mkdir classifier-poc && cd classifier-poc
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# get a key at https://aistudio.google.com/  →  put it in .env
echo "GEMINI_API_KEY=your_key_here" > .env
```

Smoke test (confirms the key + SDK work):

```python
from dotenv import load_dotenv; load_dotenv()
from google import genai
client = genai.Client()                       # picks up GEMINI_API_KEY
print(client.models.generate_content(
    model="gemini-2.5-flash", contents="say ok").text)
```

> **Model note:** currently running `gemini-2.5-flash-lite` — chosen for higher
> free-tier quota (better for iteration). Any Gemini Flash variant works; swap
> the `MODEL` constant in [classifier.py](classifier.py). The web form's model
> badge reflects it live.

---

## 7. Phase 1 — Core classifier (CLI, hard-coded input) ✅ shipped

As-shipped lives in [classifier.py](classifier.py), [extract.py](extract.py),
[categories.py](categories.py), and [run_cli.py](run_cli.py). The initial
sketch below is preserved as historical context — the shipped code adds
identifier extraction and per-category prompt guidance beyond this sketch.

`classifier.py` (initial sketch — see the file for the shipped version):

```python
import os
from typing import Literal, Optional
from pydantic import BaseModel
from google import genai
from extract import extract_text
from categories import keyword_hits

MODEL = "gemini-2.5-flash"   # confirm current free Flash model in AI Studio

Label = Literal[
    "Development / Construction", "Payment / Billing", "Lease / Occupancy",
    "Compliance / Legal", "Capital / Finance", "Vendor Performance",
    "General Governance",
]

class Classification(BaseModel):
    label: Label
    confidence: float       # 0.0–1.0, model's self-rated certainty
    rationale: str          # one short sentence

client = genai.Client()     # reads GEMINI_API_KEY from env

PROMPT = (
    "You classify real-estate / property-management emails into exactly one "
    "category. Use the sender domain, subject, keyword hits, and attachment "
    "text. Return the single best label, a confidence from 0 to 1, and a "
    "one-sentence rationale.\n\n"
)

def build_signal(sender_domain, subject, body, attachment_path):
    att = extract_text(attachment_path) if attachment_path else ""
    hits = keyword_hits(f"{subject}\n{body}\n{att}")
    signal = (f"SENDER DOMAIN: {sender_domain}\nSUBJECT: {subject}\n"
              f"KEYWORD HITS: {hits}\nATTACHMENT TEXT (truncated):\n{att[:6000]}")
    return signal, hits

def classify(sender_domain: str, subject: str, body: str = "",
             attachment_path: Optional[str] = None) -> dict:
    signal, hits = build_signal(sender_domain, subject, body, attachment_path)
    resp = client.models.generate_content(
        model=MODEL,
        contents=PROMPT + signal,
        config={
            "response_mime_type": "application/json",
            "response_schema": Classification,
            "temperature": 0,
        },
    )
    result = Classification.model_validate_json(resp.text)
    return {
        "label": result.label,
        "confidence": round(result.confidence, 2),
        "rationale": result.rationale,
        "method": "gemini",
        "keyword_hits": hits,
        "needs_review": result.confidence < 0.60,
    }
```

`run_cli.py` (hard-coded input for now):

```python
from dotenv import load_dotenv; load_dotenv()
from classifier import classify

if __name__ == "__main__":
    r = classify(
        sender_domain="brightleafretail.com",
        subject="Executed lease — Maple Crossing Suite 200",
        body="Signed lease attached for your records.",
        attachment_path="samples/Lease_Agreement_OP-142.pdf",
    )
    print(f"{r['label']}  ({r['confidence']:.0%})"
          f"{'  [needs review]' if r['needs_review'] else ''}")
    print(r["rationale"])
    print("hits:", r["keyword_hits"])
```

**Acceptance for Phase 1:** `python run_cli.py` prints a label and a confidence
for the lease PDF without errors.

---

## 8. Phase 2 — Test it ✅ shipped

Runs one case (the lease) by default to save free-tier quota; `RUN_ALL=1 python
test_cases.py` runs all 7 with a 13s delay between calls. Test data lives in
[cases.py](cases.py); both `test_cases.py` and `app.py`'s form presets read
from it — single source of truth.

**Verified result:** 7/7 correct at last full run. Vendor agreement (case 2)
correctly lands on Vendor Performance with a sensible rationale.

Case table (also encoded in [cases.py](cases.py)):

| # | sender_domain | subject | attachment | Expected label |
|---|---------------|---------|------------|----------------|
| 1 | brightleafretail.com | Executed lease — Maple Crossing | `Lease_Agreement_OP-142.pdf` | Lease / Occupancy |
| 2 | summitmechanical.com | HVAC service agreement — Northgate | `Vendor_Agreement_AS-087.pdf` | Vendor Performance *(or Compliance / Legal)* |
| 3 | apex-glass.com | Invoice #4471 due Net 30 | — | Payment / Billing |
| 4 | city-permits.gov | Permit approval — site grading | — | Compliance / Legal |
| 5 | capital-partners.com | Q3 capital call notice | — | Capital / Finance |
| 6 | gc-buildwell.com | Change order #12 — slab revision | — | Development / Construction |
| 7 | admin@ourfirm.com | Board meeting minutes — March | — | General Governance |

`test_cases.py` pattern:

```python
from dotenv import load_dotenv; load_dotenv()
from classifier import classify

CASES = [
    ("brightleafretail.com", "Executed lease — Maple Crossing", "",
     "samples/Lease_Agreement_OP-142.pdf", "Lease / Occupancy"),
    ("apex-glass.com", "Invoice #4471 due Net 30", "", None, "Payment / Billing"),
    # ... add the rest
]

passed = 0
for domain, subj, body, att, expected in CASES:
    r = classify(domain, subj, body, att)
    ok = r["label"] == expected
    passed += ok
    flag = "" if not r["needs_review"] else " [review]"
    print(f"[{'PASS' if ok else 'FAIL'}] got={r['label']} ({r['confidence']:.0%})"
          f"{flag}  expected={expected}")
print(f"\n{passed}/{len(CASES)} correct")
```

**What to check**

- Label matches expected on the unambiguous cases (1, 3–7).
- Case 2 may legitimately land on either of two labels — verify the **rationale**
  is sensible and the confidence is *lower* than the unambiguous cases. This is
  the calibration check, not a pass/fail.
- Low-confidence outputs get `needs_review = True` rather than a silently-wrong
  label.

**Watch the free-tier rate limit** — keep the test set small and run it
sparingly; cache results while iterating so you don't burn quota.

---

## 9. Phase 3 — Web form front end ✅ shipped

As-shipped lives in [app.py](app.py) + [templates/form.html](templates/form.html).
Substantially richer than the original sketch:

- **File upload** (PDF today; docx/xlsx once Phase 4 ships) — beats the sample dropdown when both are set
- **Preset dropdown** — all 7 cases from [cases.py](cases.py); selecting locks form fields
- **Clear** link — resets to a blank form
- **Post-Redirect-Get** — POST stashes result in a UUID-keyed in-memory cache and returns 303 → `/?rid=<uuid>`. GET reads-and-pops. Reload no longer re-fires the API.
- **Graceful error handling** — 429/403/API/server/unknown errors render in a red block rather than 500
- **Branded header + live model badge** pulled from `classifier.MODEL`
- **Python 3.14 compatibility fixes** — Jinja2 template cache disabled; new Starlette `TemplateResponse(request, name, ctx)` signature

Initial `app.py` sketch (preserved for reference — actual shipped version is richer):

```python
from dotenv import load_dotenv; load_dotenv()
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import classifier

app = FastAPI(title="Attachment Classifier POC")
templates = Jinja2Templates(directory="templates")

SAMPLES = {
    "Lease (OP-142)": "samples/Lease_Agreement_OP-142.pdf",
    "Vendor Agreement (AS-087)": "samples/Vendor_Agreement_AS-087.pdf",
    "No attachment": "",
}

@app.get("/", response_class=HTMLResponse)
def form(request: Request):
    return templates.TemplateResponse(
        "form.html", {"request": request, "samples": SAMPLES, "result": None})

@app.post("/classify", response_class=HTMLResponse)
def do_classify(request: Request,
                sender_domain: str = Form(...),
                subject: str = Form(...),
                body: str = Form(""),
                attachment: str = Form("")):
    result = classifier.classify(sender_domain, subject, body, attachment or None)
    return templates.TemplateResponse(
        "form.html",
        {"request": request, "samples": SAMPLES, "result": result,
         "sender_domain": sender_domain, "subject": subject, "body": body})
```

`templates/form.html` (minimal):

```html
<!doctype html><meta charset="utf-8"><title>Classifier POC</title>
<h2>Incoming email (simulated)</h2>
<form method="post" action="/classify">
  <p>Sender domain: <input name="sender_domain" value="{{ sender_domain or '' }}"></p>
  <p>Subject: <input name="subject" size="60" value="{{ subject or '' }}"></p>
  <p>Body:<br><textarea name="body" rows="4" cols="60">{{ body or '' }}</textarea></p>
  <p>Attachment:
    <select name="attachment">
      {% for label, path in samples.items() %}
      <option value="{{ path }}">{{ label }}</option>{% endfor %}
    </select></p>
  <button type="submit">Classify</button>
</form>
{% if result %}
<h3>Result</h3>
<p><b>{{ result.label }}</b> — {{ '%.0f'|format(result.confidence*100) }}%
   {% if result.needs_review %}<i>(needs review)</i>{% endif %}</p>
<p>{{ result.rationale }}</p>
<p><small>keyword hits: {{ result.keyword_hits|join(', ') }}</small></p>
{% endif %}
```

Run it:

```bash
uvicorn app:app --reload      # open http://127.0.0.1:8000
```

> **Flask instead?** Swap `app.py` for a Flask route that reads
> `request.form[...]` and calls the same `classifier.classify()` — the core
> module doesn't change. FastAPI is suggested here for the auto-generated
> `/docs` and clean form handling.

---

## 10. Definition of done (POC)

- [x] `run_cli.py` classifies the lease PDF and prints label + confidence.
- [x] `test_cases.py` runs the labeled set; unambiguous cases pass; ambiguous
      case (vendor agreement) shows a sensible rationale.
- [x] Low-confidence results are flagged `needs_review` rather than mislabeled.
- [x] The web form classifies a simulated email end to end.
- [x] Extracts `OP-####` / `AS-###` project identifiers alongside classification.

**POC is complete for PDF attachments.** Next phase adds Word document support.

## 11. Phase 4a — Word (`.docx`) attachment support 🔜 **next**

Real inboxes carry `.docx` constantly (vendor agreements, letters, memos).
This phase extends `extract.py` to handle it. The classifier does **not**
change — `classify()` already treats `extract_text()` output as an opaque
text blob.

**Note:** Excel (`.xlsx`) is split out into Phase 4b (deferred). Doing docx
first keeps the surface small and lets us prove the dispatcher pattern
before adding the spreadsheet flattening logic (which has its own token /
layout tradeoffs).

### Approach

Refactor `extract.py` into a dispatcher on file extension:

| Extension | Library | Notes |
|---|---|---|
| `.pdf` | `pdfplumber` → `pypdf` fallback | already implemented |
| `.docx` | `python-docx` | extract paragraphs **and** table cells (missing tables is the classic mistake) |
| `.doc` (legacy) | — | out of scope. Return `""` + log. Needs LibreOffice headless or `pywin32`. |
| anything else | — | return `""` |

### Implementation sketch

- Add `python-docx` to `requirements.txt`
- Split `extract.py` into `extract_text()` dispatcher + `_extract_pdf`, `_extract_docx`
- `_extract_docx` iterates both `doc.paragraphs` and `doc.tables` (cells → newline-joined rows)
- Apply a soft per-file cap (~50k chars) before the existing 6000-char signal truncation in `build_signal()`
- Update the file-upload input's `accept` attribute in the form to include `.docx`

### Test additions

- Add one `.docx` sample to `samples/` (e.g. a vendor agreement in Word matching the existing PDF vendor case)
- Add a corresponding case to [cases.py](cases.py) → `Vendor Performance` or `Compliance / Legal`
- Verify the identifier regex still finds `OP-####` / `AS-###` inside extracted docx text

### Acceptance

- Upload a `.docx` in the web form → gets classified with sensible label + rationale
- The new test case passes when run via `test_cases.py`
- Extracted text includes both paragraph and table content (verify with a docx that has a table)

### Open decisions

1. Generate the sample `.docx` programmatically or use a real one?
2. Confirm 50k-char per-file extraction cap.
3. Legacy `.doc` stays out of scope — confirm.

---

## 12. Phase 4b — Excel (`.xlsx`) attachment support (deferred)

Same dispatcher pattern. Uses `openpyxl` to walk sheets and flatten each row
as tab-joined cells, prefixed with the sheet name.

**Design note — spreadsheets aren't prose.** For classification we only need
keywords to surface, so flattening `Sheet: Invoices\n4471\tNet 30\t$12,400`
is enough. Do **not** try to preserve layout.

**Watch for:** a 50-sheet financial model blowing past the 50k-char per-file
cap. Truncate at the sheet boundary rather than mid-row.

Deferred until docx is in and stable.

---

## 13. Phase 5 — Multiple attachments per email (deferred)

Real emails often carry several attachments (e.g. an invoice PDF + a backup
spreadsheet). The POC currently accepts **one** attachment path; this phase
extends the system to handle N.

### Design questions to settle first

1. **One label per email, or one per attachment?** Most likely "one label per
   email" — an email is a single event in the property-manager's workflow. So
   attachments get concatenated into the signal text, not classified
   independently. Multi-label per email is a different product.
2. **Concatenation strategy.** Each attachment's extracted text is prefixed
   with `--- ATTACHMENT: {filename} ---` so the model can tell them apart and
   reference them in the rationale.
3. **Token budget.** The current 6000-char attachment truncation in
   `build_signal()` has to become a *total* budget split across N attachments —
   either even split (`6000 / N` each) or first-come-first-served. Probably
   first-come, since the first attachment is usually the primary one.
4. **Keyword hits aggregation.** `keyword_hits()` already operates on a single
   text blob — feed it the concatenated text; no change needed.
5. **UI.** The form's file input becomes `<input type="file" multiple>` and
   the sample dropdown becomes a multi-select (or a checkbox list of samples).
   The result UI lists which files contributed.

### Implementation sketch

- `classifier.classify()` signature changes from
  `attachment_path: Optional[str]` to `attachment_paths: list[str] | None`.
  Keep a single-path shim for backwards compatibility with `run_cli.py` and
  `test_cases.py`.
- `build_signal()` loops over paths, calls `extract_text()` per file, and
  emits a labeled block per attachment.
- FastAPI route accepts `List[UploadFile]`; each file gets a temp path; all
  paths cleaned up in `finally`.
- Test cases gain a "multi-attachment" row (e.g. invoice PDF + payment
  spreadsheet → Payment / Billing).

### Open decisions

1. Confirm "one label per email" (not per attachment).
2. Confirm first-come truncation strategy for the 6000-char budget.
3. Confirm UI pattern: multi-file upload + multi-select samples (vs. a
   separate "attachments" repeating row).

---

## 14. Phase 6 — Project / Deal / Asset identifier extraction ✅ shipped

Most emails reference a specific deal or asset by an internal code. We extract
that code alongside the category so downstream automation can route the email
to the right Monday.com / SharePoint record.

### Identifier scheme

- **`OP-####`** — a Deal (Opportunity / Project). 3+ digits.
- **`AS-###`** — an Asset. 3+ digits.

(Pattern is case-insensitive; we normalize to upper-case in output.)

### How it works

1. **Regex pre-pass** (`find_identifiers()` in [classifier.py](classifier.py))
   scans the assembled signal text — subject + body + attachment text — for
   all `OP-####` / `AS-###` matches. Returns deduped, order-preserved list of
   candidates. Cheap and deterministic.
2. **Candidates fed to the prompt** under an `IDENTIFIER CANDIDATES:` line so
   Gemini can see exactly what the regex found.
3. **Pydantic schema extended** with `identifier: Optional[str]` and
   `identifier_rationale: str`. Gemini picks the best candidate (usually the
   one mentioned in the subject, or the first one referenced in the
   attachment), or returns `null` if nothing relevant was found.
4. **Output** includes `identifier`, `identifier_rationale`, and the raw
   `identifier_candidates` list (useful for debugging when the model picks
   something unexpected).

### Edge cases handled / to watch

- **No identifier found:** `identifier` is `null`, `identifier_rationale`
  explains "no identifier found".
- **Multiple candidates:** model is told to pick the *best* one (subject
  beats body beats attachment). When it's ambiguous, the rationale should
  explain *why* that one was chosen.
- **False positives** (e.g. "OP-100" appearing in boilerplate): the rationale
  field is the user-facing audit trail — if the model picks something weird,
  the rationale exposes that.
- **New ID formats** (e.g. property codes, vendor IDs) can be added to the
  regex without touching the schema.

---

## 15. Phase 7 — JSON webhook API + routing hints 🔜 **next**

The web form has taken us as far as manual demos can go. To automate the
Monday intake flow, the service needs to be **callable** by Power Automate,
Zapier, or a plain HTTP client — not just usable through a browser form.

This phase adds a JSON `POST /api/classify` endpoint alongside the existing
form UI. The form stays as a demo/QA surface; the API becomes the
integration point.

### Goals

1. External orchestrators (Zapier/Power Automate/curl) can call the service and get JSON back.
2. Response includes **routing hints** (SharePoint folder path + Monday board/group + priority) so downstream can create intake items without further logic.
3. Endpoint is auth-gated (bearer token from env var) — no accidental open surface.
4. Response shape is **already list-based** on attachments (`attachments: [...]`) so Phase 5 (multi-attachment) just lifts a cap, no shape churn later.

### Request shape

```json
POST /api/classify
Authorization: Bearer <API_TOKEN>
Content-Type: application/json

{
  "sender_domain": "gc-buildwell.com",
  "subject": "Change order CO-12 — Riverbend Commons",
  "body": "See attached...",
  "attachments": [
    {
      "filename": "Change_Order_OP-215.docx",
      "content_base64": "<base64 bytes>"
    }
  ]
}
```

- `attachments` is a list, but capped at 1 entry for this phase (Phase 5 lifts the cap).
- If `attachments` is empty, the classifier runs on subject + body only — same behavior as the web form's "— none —" sample. The response's `attachments[0]` uses `"(email body)"` as a sentinel filename so downstream consumers don't need to branch on the zero-attachment case.

### Response shape

The **email is the unit of classification** — one call returns one label,
one identifier, and one set of routing hints, ready to become one Monday
intake item. Attachments are evidence: each is scanned for project
identifiers (so multi-project emails can be flagged for human triage) but
never individually classified.

```json
{
  "email": {
    "sender_domain": "gc-buildwell.com",
    "subject": "Change order CO-12 — Riverbend Commons",
    "body_length": 42,

    "label": "Development / Construction",
    "confidence": 0.98,
    "rationale": "...",

    "identifier": "OP-215",
    "identifier_rationale": "...",
    "identifier_candidates": ["OP-215"],

    "keyword_hits": ["change order", "site work"],
    "priority_hint": "High",
    "monday_board_hint": "Construction Intake",
    "monday_group_hint": null,
    "sharepoint_folder": "/Deals/01_Active_Deals/OP-215",

    "multiple_projects_detected": false,
    "needs_review": false,
    "needs_review_text": "No",
    "review_reasons": []
  },
  "attachments_analyzed": [
    {
      "filename": "Change_Order_OP-215.docx",
      "size_bytes": 36428,
      "identifiers_found": ["OP-215"]
    }
  ],
  "model": "gemini-2.5-flash"
}
```

**Triage flags:**

- `multiple_projects_detected` — true when >1 distinct identifier appears
  across subject + body + attachments. The classifier picks the best single
  identifier anyway; the human decides whether to split the intake item at
  approval time. `attachments_analyzed[i].identifiers_found` shows which
  file references which project, making the split actionable.
- `needs_review` — true when `review_reasons` is non-empty. Downstream
  branches on this boolean; `review_reasons` explains why with stable slugs:
  `low_confidence` (model confidence below threshold) and
  `multiple_projects_detected`.

### Routing hint logic (all deterministic, no external calls)

Lives in a new `routing.py` module. Pure functions of `(label, identifier, keyword_hits, sender_domain)`:

| Hint | Rule |
|---|---|
| `sharepoint_folder` | `identifier` starts with `OP-` → `/Deals/01_Active_Deals/OP-###`. Starts with `AS-` → `/Assets/AS-###`. Null → `/Intake/{sender_domain}/` |
| `monday_board_hint` | Category → board name (matches Exhibit A step 4 mapping — see governance map below) |
| `monday_group_hint` | Category → group within board (nullable) |
| `priority_hint` | `High` if any keyword hit is in `{invoice, pay application, change order, survey, inspection, approval, permit}`; else `Normal` — title-cased to map directly onto Monday status labels |

**Governance map** (illustrative — actual board names will match the client's Monday workspace):

| Category | Monday board hint | Monday group hint |
|---|---|---|
| Development / Construction | Construction Intake | — |
| Payment / Billing | Construction Intake | Payment Review |
| Lease / Occupancy | Asset Management Intake | — |
| Compliance / Legal | Compliance Intake | — |
| Capital / Finance | Development Intake | — |
| Vendor Performance | Construction Intake | Vendor Performance |
| General Governance | General Governance Intake | — |

### Auth

- New env var `API_TOKEN` — a random string set on Render.
- Endpoint reads `Authorization: Bearer <token>` header and matches exact string.
- If `API_TOKEN` is not set at process start, the endpoint returns `500` with a clear message. Fail closed, never fail open.
- The HTML form + `/classify` route stay unauthenticated (they're for local/demo use; not exposed to the public internet if the operator keeps the Render URL private, which is the current state).

### Error responses

Consistent JSON error shape: `{"error": "...", "code": "..."}`.

- `400` — bad request (no attachments, invalid base64, missing required fields)
- `401` — invalid or missing bearer token
- `413` — attachment too large (soft cap: 10 MB per file)
- `422` — pydantic validation error (auto-generated by FastAPI)
- `500` — server error, missing `API_TOKEN`, or Gemini failure
- `502` / `503` — upstream Gemini error (mapped from `google.genai.errors.ServerError`)

### Implementation checklist

- [ ] Add `routing.py` with `sharepoint_folder_for`, `monday_hints_for`, `priority_for`, and a top-level `compute_routing()` function
- [ ] Add `schemas.py` (or inline in `app.py` — decide) with pydantic `AttachmentIn`, `ClassifyRequest`, `AttachmentResult`, `ClassifyResponse`
- [ ] Add `POST /api/classify` route in `app.py` — bearer check, base64 decode → temp file, call `classifier.classify()`, layer `routing.py` output onto the result, build `summary`
- [ ] Read `API_TOKEN` from env; fail closed if unset
- [ ] Update `.env.example` (create if missing) to show `API_TOKEN=...`
- [ ] Update `README` or PROGRESS.md with a curl example
- [ ] Add a quick smoke test (either extend `test_cases.py` or a new `test_api.py`) that exercises the endpoint with the docx sample base64'd
- [ ] Set `API_TOKEN` env var on Render before merging

### Acceptance

- `curl` a classify request against a local uvicorn instance → get back JSON with `label`, `identifier`, and `routing.sharepoint_folder` populated correctly.
- Endpoint refuses requests missing or wrong bearer token with `401`.
- Endpoint refuses requests missing `attachments` with `400`.
- Existing web form still works (unchanged behavior).
- Existing test suite still passes.

### Out of scope for this phase

- Multi-attachment (Phase 5 lifts the cap; response shape already supports it).
- Idempotency (`(messageId, sha256(attachment))` de-dup) — deferred until a real orchestrator is calling the endpoint and duplicates become a real observed problem.
- Rate limiting on the API endpoint — Gemini's own rate limit is the current backpressure.
- OAuth or key rotation — bearer token from env is enough for the POC.
- Async / callback mode — sync response works within Zapier/PA timeouts for single-attachment calls.

---

## 16. Out of scope (deliberately) / next steps

For the POC:

- Real email ingestion (Exchange/Graph/IMAP polling)
- Project resolution against a real registry (fuzzy match on names/addresses)
- Writing results to Monday.com / SharePoint
- Confidence calibration and a deterministic keyword-vs-LLM tie-breaker
- Multi-attachment per email (planned as Phase 5)

The POC intentionally proves the *classification brain* in isolation. The
downstream MVP (email capture → SharePoint filing → Monday intake, with a
triage lane) is described in a separate outline; this POC exists to
de-risk the AI piece so that outline's classifier + identifier steps have
already been proven.