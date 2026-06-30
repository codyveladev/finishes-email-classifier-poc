# PLAN.md — Email Attachment Classifier (Proof of Concept)

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

**Output**

```json
{ "label": "Lease / Occupancy", "confidence": 0.91, "rationale": "...", "method": "gemini", "keyword_hits": ["lease", "tenant", "premises"] }
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
inputs ──► assemble signal text ──► keyword pre-pass ──► Gemini (structured) ──► result
           (domain+subject+         (cheap candidate     (enum label +
            attachment text)         + hit list)          confidence + rationale)
```

1. **Assemble signal text** — concatenate sender domain, subject, body, and the
   extracted attachment text into one block.
2. **Keyword pre-pass** — scan the block against the cue lists; record hits and a
   cheap candidate. Fast, explainable, and useful as a sanity check / fallback.
3. **Gemini call** — send the signal text with a constrained schema; the model
   returns the label (as an enum), a confidence (0–1), and a one-line rationale.
4. **Combine & emit** — return the label + confidence. If confidence is below a
   threshold (e.g. `0.60`), flag `needs_review` instead of trusting the label.

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

## 5. Project structure

```
classifier-poc/
├── .env                  # GEMINI_API_KEY=...
├── requirements.txt
├── categories.py         # the 7 labels + keyword cue map
├── extract.py            # attachment path -> text (PDF, OCR fallback)
├── classifier.py         # keyword pre-pass + Gemini call -> result   ← the core
├── run_cli.py            # Phase 1: hard-coded inputs, prints label + confidence
├── test_cases.py         # sample inputs + expected labels (Phase 2)
├── app.py                # Phase 3: FastAPI form front end (added LAST)
├── templates/
│   └── form.html
└── samples/
    ├── Lease_Agreement_OP-142.pdf
    └── Vendor_Agreement_AS-087.pdf
```

Drop the two PDFs already generated into `samples/`.

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

> **Model note:** `gemini-2.5-flash` is a safe, free-tier-eligible default.
> A newer Flash model (e.g. `gemini-3.5-flash`) may also be on the free tier —
> check the model list in AI Studio and set `MODEL` accordingly. Keep it in one
> constant so it's a one-line swap.

---

## 7. Phase 1 — Core classifier (CLI, hard-coded input)

Build `extract.py`, then `classifier.py`, then `run_cli.py`.

`classifier.py` (the important part):

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

## 8. Phase 2 — Test it

Use `test_cases.py` to run a small labeled set and check accuracy. Mix
attachment-driven cases with subject-only cases (no attachment) to prove both
paths.

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

## 9. Phase 3 — Web form front end (add this LAST)

A form that **mimics receiving an email**: fields for sender domain, subject,
body, and an attachment (a dropdown of the sample files for now). On submit it
runs the *same* `classifier.classify()` and shows the label + confidence +
rationale. The core stays untouched — the web layer is a thin wrapper.

`app.py` (FastAPI):

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

- [ ] `run_cli.py` classifies the lease PDF and prints label + confidence.
- [ ] `test_cases.py` runs the labeled set; unambiguous cases pass; ambiguous
      case (vendor agreement) shows a sensible rationale and lower confidence.
- [ ] Low-confidence results are flagged `needs_review` rather than mislabeled.
- [ ] The web form classifies a simulated email end to end.

## 11. Phase 4 — Word + Excel attachment support (planned)

PDF only is fine for the POC, but real inboxes carry `.docx` and `.xlsx`
attachments constantly (rent rolls, invoices, vendor agreements, budgets).
This phase extends `extract.py` to handle them. The classifier itself does
not change — `classify()` already calls `extract_text(path)` and treats the
result as a blob of text.

### Approach

Dispatch on file extension inside `extract_text()`:

| Extension | Library | Notes |
|---|---|---|
| `.pdf` | `pdfplumber` → `pypdf` fallback | already implemented |
| `.docx` | `python-docx` | extract paragraphs **and** table cells (easy to miss tables) |
| `.xlsx` | `openpyxl` | iterate sheets; flatten each row as tab-joined cells; prefix with sheet name |
| `.csv` | stdlib `csv` | read rows as text |
| `.doc` / `.xls` (legacy) | — | **out of scope.** Return `""` + log a warning. Needs LibreOffice headless or `pywin32`; real-estate folks still send these so revisit later. |
| anything else | — | return `""` |

### Design notes

- **Excel "text" is awkward.** Spreadsheets aren't prose. For classification we
  only need keywords to surface, so flattening `Sheet: Invoices\n4471\tNet 30\t$12,400`
  is enough. Do **not** try to preserve layout.
- **Token budget.** A 50-sheet financial model could blow past the 6000-char
  signal truncation. Add a soft per-file cap (~50k chars) at extraction time
  before the existing truncation in `build_signal()`.
- **Word tables.** `python-docx` exposes `.paragraphs` and `.tables` separately;
  iterate both or table content is silently dropped.
- **Refactor.** Split `extract.py` into an `extract_text()` dispatcher plus
  `_extract_pdf`, `_extract_docx`, `_extract_xlsx`, `_extract_csv` helpers.

### Requirements additions

```
python-docx
openpyxl
```

### Test additions

Phase 2 currently covers PDF + no-attachment only. To prove the new paths,
add at least:

- one `.docx` case (e.g. a vendor agreement in Word) → Vendor Performance
- one `.xlsx` case (e.g. a rent roll or invoice spreadsheet) → Payment / Billing or Lease / Occupancy

Sample files can be generated programmatically or dropped in by hand.

### Open decisions

1. Generate sample `.docx` / `.xlsx` programmatically, or use real-world examples?
2. Confirm legacy `.doc` / `.xls` stay out of scope for now.
3. Confirm 50k-char per-file extraction cap (before the 6k signal truncation).

---

## 12. Phase 5 — Multiple attachments per email (planned)

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

## 13. Phase 6 — Project / Deal / Asset identifier extraction ✅

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

## 14. Out of scope (deliberately) / next steps

- Real email ingestion (Gmail/IMAP polling), file upload instead of a fixed path.
- Project resolution (OP-### / AS-### + address matching).
- Writing results to Monday.com / SharePoint.
- Confidence calibration and a deterministic keyword-vs-LLM tie-breaker.