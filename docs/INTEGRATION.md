# INTEGRATION.md — How the live system is wired

The end-to-end pipeline as actually built and running: a real email arrives at
a shared Outlook mailbox and ends as a governed item on a Monday intake board.

This is reference material — the *why* behind each choice, and the traps that
cost real hours. [PROGRESS.md](PROGRESS.md) is the build log;
[PLAN.md](PLAN.md) is the classifier's own plan.

---

## 1. The shape

```
Outlook shared mailbox
        │
        ▼
POWER AUTOMATE ──────────────────────────────────┐
  · trigger on new email                         │  stays inside the
  · filter inline/signature images               │  Microsoft tenant
  · upload attachments to SharePoint holding     │
        │                                        │
        │  POST /api/classify  (base64)          │
        ▼                                        │
CLASSIFIER SERVICE (Render)                      │
  · extract text from PDF / Word                 │
  · keyword pre-pass + identifier regex          │
  · Gemini classification                        │
  · routing hints + triage flags                 │
        │                                        │
        │  JSON response                         │
        ▼                                        │
POWER AUTOMATE                                   │
  · parse response                               │
  · flatten to a 9-field payload  ───────────────┘
        │
        │  POST to Zapier Catch Hook
        ▼
ZAPIER
  · Code step: parse payload
  · Monday: Create Item
        │
        ▼
Monday — Construction Intake Board
```

### Why the work is split this way

| Concern | Platform | Reason |
|---|---|---|
| Outlook trigger, attachments, SharePoint | **Power Automate** | Native in-tenant connectors. Documents never leave Microsoft 365. Zapier physically cannot deliver multi-attachment emails — see §6. |
| Classification | **This service** | Stateless decision engine. Any caller gets the same answer. |
| Monday item creation | **Zapier** | Monday's Power Automate connector is ~$60/mo. Zapier is already licensed and already has the connector. |

**The Zapier hop carries metadata only** — subject, sender, category, rationale.
The attachments themselves never touch it. If a compliance reviewer objects
later, swap that one HTTP action for a direct Monday GraphQL call (§8);
nothing else changes. It's a seam, not debt.

---

## 2. Power Automate flow

```
1. When a new email arrives in a shared mailbox (V3)
2. Filter Inline Attachments
3. Initialize AttachmentsArray        (Array, empty)
4. Initialize FolderPath              (String, empty)
5. Condition — Attachments Exist
     True:
       Create new folder
       Set variable FolderPath
       Apply to each
         Get Attachment (V2)
         Append to AttachmentsArray
         Create file
     False: (empty)
6. HTTP — POST /api/classify
7. Parse JSON
8. Compose — Zapier payload
9. HTTP — POST to Zapier Catch Hook
```

### 1. Trigger

**When a new email arrives in a shared mailbox (V3)**

- Mailbox: the department alias
- **Include Attachments: Yes** ← without this `contentBytes` is empty
- **Only with Attachments: No** ← subject-only emails must still flow through

### 2. Filter Inline Attachments

Drops signature logos, which Outlook reports as real attachments.

- **From:** `coalesce(triggerOutputs()?['body/attachments'], json('[]'))`
  The `coalesce` matters — the trigger returns null (not `[]`) when there are
  no attachments, and Filter array errors on null.
- **Where:** `item()?['isInline']` is equal to `false`

### 3–4. Variables

Both must be at **top level**. Power Automate rejects `Initialize variable`
inside a condition or loop.

| Name | Type | Purpose |
|---|---|---|
| `AttachmentsArray` | Array | the `{filename, content_base64}` list sent to the classifier |
| `FolderPath` | String | the SharePoint folder, so the Zapier payload can link to it |

Variables are **globally scoped** — unlike action outputs, they can be written
inside a branch and read outside it. That's the entire reason this design works;
an earlier attempt using Compose + `coalesce` failed because
`Attachments final` couldn't reference a Compose living inside the True branch.

### 5. Condition — Attachments Exist

`empty(body('Filter_Inline_Attachments'))` is equal to `false`

The condition only guards SharePoint work. The classifier handles zero
attachments natively (`attachments: []` → classify on subject + body), so no
branching is needed for the API call.

**Inside True, in this order:**

| Action | Field | Value |
|---|---|---|
| **Create new folder** | Folder Path | `/Intake/{department}/{yyyy-MM-dd}_{id fragment}` |
| **Set variable** | FolderPath | dynamic content → **Full Path** |
| **Apply to each** | Select an output | `body('Filter_Inline_Attachments')` |
| ├ **Get Attachment (V2)** | Message Id | `triggerOutputs()?['body/id']` |
| | Attachment Id | `item()?['id']` |
| ├ **Append to AttachmentsArray** | Value | see §3 — **this is the trap** |
| └ **Create file** | Folder Path | dynamic content → **Full Path** |
| | File Name | `item()?['name']` |
| | File Content | dynamic content → **Content Bytes** (no expression) |

Folder creation must precede the loop, and `Create file` must sit *inside* the
same loop as `Get Attachment` — otherwise `Get Attachment` is out of scope and
every file gets the last iteration's content.

### 6. HTTP — classifier

| Field | Value |
|---|---|
| Method | `POST` |
| URI | `https://<render-url>/api/classify` |
| Headers | `Authorization: Bearer <API_TOKEN>`, `Content-Type: application/json` |

**Body:**
```json
{
  "sender_domain": "@{last(split(triggerOutputs()?['body/from'], '@'))}",
  "subject": "@{triggerOutputs()?['body/subject']}",
  "body": "@{triggerOutputs()?['body/bodyPreview']}",
  "attachments": "@variables('AttachmentsArray')"
}
```

- `attachments` uses a **single `@`**, not `@{...}`. Braces stringify the array
  and the API returns 422.
- `last(split(...))` rather than `split(...)[1]` — addresses can contain more
  than one `@`.
- **Settings → Secure Inputs: On** keeps the token out of run history.

### 7. Parse JSON

- **Content:** `body('HTTP')`
- **Schema:** the one in [API_TEST_CASES.md](API_TEST_CASES.md) — paste it,
  don't generate it. A generated schema types `identifier` as `string` and then
  **fails on every email without a project code**. It must be
  `["string", "null"]`, same for `monday_group_hint`.

### 8. Compose — Zapier payload

Flat. Arrays joined. Zapier's field picker chokes on nested objects.

```json
{
  "item_name": "@{triggerOutputs()?['body/subject']}",
  "classification": "@{body('Parse_JSON')?['email']?['label']}",
  "vendor": "@{triggerOutputs()?['body/from']}",
  "notes": "@{triggerOutputs()?['body/bodyPreview']}",
  "priority": "@{body('Parse_JSON')?['email']?['priority_hint']}",
  "sharepoint_link": "@{variables('FolderPath')}",
  "confidence": "@{body('Parse_JSON')?['email']?['confidence']}",
  "rationale": "@{body('Parse_JSON')?['email']?['rationale']}",
  "needs_review": "@{body('Parse_JSON')?['email']?['needs_review_text']}"
}
```

`item_name`, `vendor`, `notes`, and `sharepoint_link` come from Power Automate,
not the classifier — the API returns `body_length`, never the body itself, and
has no idea where the files were filed.

### 9. HTTP — Zapier

| Field | Value |
|---|---|
| Method | `POST` |
| URI | the Zapier Catch Hook URL |
| Headers | `Content-Type: application/json` |
| Body | Expression tab → `outputs('Compose_Zapier_payload')` |
| **Settings → Content Transfer** | **Allow chunking: Off** |

**Chunking off is required.** Large email bodies trip Power Automate into a
chunked upload, which expects a `Location` header in the response. Zapier's
webhook doesn't send one, and the run fails with *"The response to partial
content upload initiating request is not valid."*

---

## 3. The binary trap (read this before touching `contentBytes`)

`Get Attachment (V2)` returns `contentBytes` as a **binary-typed field**.
Power Automate coerces it differently depending on how you reference it, and
**two of the three forms are silently wrong**.

| Expression | What arrives | Result |
|---|---|---|
| `@{body('Get_Attachment_(V2)')?['contentBytes']}` | **Decoded** — raw `%PDF-1.4…` text, lossy (non-UTF8 bytes → `U+FFFD`) | JSON breaks on embedded quotes/newlines |
| `base64(body('Get_Attachment_(V2)')?['contentBytes'])` | **Double-encoded** — base64 of the base64 | 200 OK, garbage content, **silent failure** |
| **Inside `concat()`, no wrapper** | **Clean base64** | ✓ |

**The working Append value** (Expression tab, whole value as one expression):

```
json(concat('{"filename":"', item()?['name'], '","content_base64":"', body('Get_Attachment_(V2)')?['contentBytes'], '"}'))
```

`concat()` receives `contentBytes` as a function argument, which skips the
string coercion that `@{...}` triggers.

**Meanwhile SharePoint wants the opposite** — the binary object itself,
untouched:

```
Create file → File Content → dynamic content → Content Bytes
```

No `base64ToBinary()`, no `$content`, no expression at all. Same field, two
consumers, two incompatible forms.

### How to tell which failure you're in

Check `content_base64` in the classifier's HTTP request body:

| Prefix | Meaning |
|---|---|
| `JVBERi0xLjQK` | ✓ correct — `%PDF-1.4` encoded once |
| `SlZCRVJpMHhM` | ✗ double-encoded — remove `base64()` |
| `%PDF-1.4` | ✗ decoded — you're using `@{...}` |

### The byte-math diagnostic

Double-encoding is invisible in the response — you get a 200 and a plausible
classification. The tell is in `attachments_analyzed`:

```json
{"filename": "Lease_Agreement_OP-142.pdf", "size_bytes": 7112, "identifiers_found": []}
```

The real PDF is **5334** bytes. Its base64 text is **7112** bytes — an exact
match. So the API decoded once, got the base64 *text* instead of a PDF, saved
that as `.pdf`, and pdfplumber found nothing to read.

`identifiers_found: []` on a file literally named `..._OP-142.pdf` is the
loudest possible signal that extraction is broken. The classifier's rationale
gives it away too: *"extracted from the **name** of the attached document."*

**Rule of thumb:** `size_bytes` ≈ 1.33 × the real file size means
double-encoding.

---

## 4. Zapier

**1. Trigger — Webhooks by Zapier → Catch Hook.** Copy the URL into Power
Automate step 9. Run the flow once so Zapier catches a sample.

**2. Code by Zapier → Run Python.** Input Data: `payload` → the raw body.

```python
import json

data = json.loads(input_data['payload'])

output = {
    'item_name': data.get('item_name', ''),
    'classification': data.get('classification', ''),
    'vendor': data.get('vendor', ''),
    'notes': data.get('notes', ''),
    'priority': data.get('priority', 'Normal'),
    'sharepoint_link': data.get('sharepoint_link', ''),
    'confidence': data.get('confidence', ''),
    'rationale': data.get('rationale', ''),
    'needs_review': data.get('needs_review', 'No'),
}
```

**3. Monday.com → Create Item.** Board: Construction Intake (`18420255812`).

| Board column | Field |
|---|---|
| Item Name | `item_name` |
| Classification | `classification` |
| Vendor | `vendor` |
| Notes | `notes` |
| Priority | `priority` |
| SharePoint Link | `sharepoint_link` |
| Classifier Confidence | `confidence` |
| Classification Rationale | `rationale` |
| Needs Classification Review | `needs_review` |
| Department Approval Status | literal `Pending` |
| Status | literal `Intake` |

---

## 5. Verified behaviour

A real email with three PDFs — `Permit_Approval_OP-118.pdf`,
`Lease_Agreement_OP-142.pdf`, `Vendor_Agreement_AS-087.pdf` — produces:

- all three files in a dated SharePoint holding folder, previewable
- text extracted from **inside** each PDF, not guessed from filenames
- `identifier_candidates: ["OP-118", "OP-142", "AS-087"]`
- `multiple_projects_detected: true` → `needs_review: "Yes"`
- an intake item on the Monday board with classification, rationale, priority,
  and a link to the folder

The multi-project flag doing its job — three projects in one email, surfaced
for a human instead of silently filed against one — is the behaviour the whole
design exists for.

---

## 6. Why not Zapier for the mailbox

Established by testing, not assumption. Zapier's Outlook trigger returns a
**hydration token**, not the file:

```
hydrate|||.eJytUN1umzAUfhdfJxGg0kCkSnNCoFSQhJasa26QMQ54gE3ALLAq...|||hydrate
```

| Attempt | Result |
|---|---|
| Fetch it in a Code step | Code steps never hydrate — they get the literal token text |
| Webhook Custom Request, file in the data payload | Token forwarded as text; service rejected it: *"Expected UploadFile, received: str"* |
| Webhook POST, file in the data payload | Same |
| Webhook POST, dedicated **File** field | The only hydrating path — documented as *"a file **object**"*, singular |

A real intake email carries several documents. A platform that forwards one
file at a time either drops attachments or examines each in isolation, which
destroys multi-project detection — the exact failure the governance system
exists to prevent.

Full write-up for the client: `Platform_Recommendation_Email_Intake.docx`.

---

## 7. Known gaps

- **Nothing surfaces the triage detail.** The board has no column for
  `review_reasons` or `identifier_candidates`, so a reviewer sees
  *Needs Review = Yes* without being told it's because the email spans
  OP-118, OP-142, and AS-087. Two columns would fix it.
- **Filenames aren't scanned for identifiers.** `Permit_Approval_OP-118.pdf`
  obviously contains `OP-118`, but the regex only reads text *inside* files.
  Free signal, currently discarded.
- **No idempotency.** Power Automate retries and forwarded chains will create
  duplicate intake items. Needs `sha256(sender_domain + attachment_bytes)` in
  Azure Table Storage.
- **Attachments stay in holding.** The "move to `/Deals/OP-###` on approval"
  step isn't built. The API already returns the target path as
  `email.sharepoint_folder`; nothing consumes it yet.
- **Gemini is external.** Even with the service hosted in Azure, extracted
  attachment text goes to Google. If all document content must stay in the
  client's boundary, that's Azure OpenAI — a config change, not a rebuild,
  and the original architecture named it.
- **Service is on Render free tier.** Sleeps after 15 minutes, so the first
  email of the day waits ~30s. Production belongs in the client's Azure
  subscription (~$13/mo App Service).

---

## 8. If the Zapier hop has to go

Replace step 9 with a direct Monday GraphQL call. **Only that one action
changes.**

| Field | Value |
|---|---|
| URI | `https://api.monday.com/v2` |
| Headers | `Authorization: <token>` (no "Bearer"), `Content-Type: application/json`, `API-Version: 2024-10` |

```json
{
  "query": "mutation ($boardId: ID!, $itemName: String!, $columnValues: JSON!) { create_item(board_id: $boardId, item_name: $itemName, column_values: $columnValues) { id } }",
  "variables": {
    "boardId": "18420255812",
    "itemName": "@{triggerOutputs()?['body/subject']}",
    "columnValues": "@{string(outputs('Compose_column_values'))}"
  }
}
```

Two things that bite:

- **`string()` on the column values is mandatory.** Monday wants
  `column_values` as an escaped JSON *string*, not an object.
- **Monday returns 200 on GraphQL errors.** Failures come back as
  `{"errors": [...]}` with a success status. Add a Condition checking
  `contains(string(body('HTTP')), 'errors')` or you'll get silent failures.

Get column IDs with:
```graphql
query { boards(ids: 18420255812) { columns { id title type } } }
```
