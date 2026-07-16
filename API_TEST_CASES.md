# API Test Cases — `POST /api/classify`

Zero-attachment cases only (`"attachments": []`) — every case below can be run
from Zapier, Power Automate, a test form, or curl without a file in hand.
Multi-attachment cases come with Phase 5.

**Endpoint:** `POST https://<render-url>/api/classify`
**Headers:** `Authorization: Bearer <API_TOKEN>` · `Content-Type: application/json`

Curl template (swap in each case's payload):

```bash
curl -X POST https://RENDER_URL/api/classify \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '<payload>'
```

> Confidence values are the model's self-report and will vary run to run.
> Treat the expected confidence as a ballpark; the fields that must match
> exactly are `label`, `identifier`, the routing hints, and the review flags.

---

## Form input table (copy-paste)

Each row is the three fields to enter into your form. Leave the attachment
empty for all of these.

| # | `sender_domain` | `subject` | `body` |
|---|---|---|---|
| 1 | `admin@ourfirm.com` | `Board meeting minutes — March` | `Attached are the minutes from the March board meeting for approval. Please review the resolutions and confirm the policy updates before the next session.` |
| 2 | `apex-glass.com` | `Invoice #4471 due Net 30` | `Please remit payment for the storefront glazing scope. Invoice #4471 attached, Net 30 terms, remittance details on page 2.` |
| 3 | `city-permits.gov` | `Permit approval — site grading` | `The site grading permit for your project has been approved. The permit certificate and inspection schedule are attached; please post on site before work begins.` |
| 4 | `capital-partners.com` | `Q3 capital call notice` | `This is your Q3 capital call notice. Please review the attached distribution schedule and wire your equity contribution by the due date noted in the notice.` |
| 5 | `gc-buildwell.com` | `Change order #12 — OP-215 slab revision` | `Change order #12 for OP-215 covers the revised slab depth on Level 1 per the updated structural drawings. No schedule extension is requested; mobilization costs are included.` |
| 6 | `brightleafretail.com` | `Executed lease — Maple Crossing Suite 200 (OP-142)` | `The executed lease for Maple Crossing Suite 200 (OP-142) is attached. Tenant takes occupancy June 1 and rent commences per Section 4 of the agreement.` |
| 7 | `assetops@ourfirm.com` | `Q3 vendor scorecard — Summit Mechanical (AS-087)` | `Q3 KPI scorecard for Summit Mechanical at AS-087: 78% on-time work order completion against a 95% target, three SLA breaches on emergency response, 12 escalations. Recommend a performance improvement plan before contract renewal.` |
| 8 | `gc-buildwell.com` | `Invoices for Riverbend (OP-215) and Northgate (OP-142)` | `Two invoices attached: Invoice #5102 covers the OP-215 slab work and Invoice #5103 covers the OP-142 storefront package. Please process both under Net 30.` |
| 9 | `outlook.com` | `Following up` | `Hi, just circling back on the thing we discussed last week. Let me know how you want to proceed and I can send over the rest.` |

Cases 10–12 are error cases (auth / validation) — see the bottom of this doc.

---

## 1. General Governance — board minutes

**Payload**

```json
{
  "sender_domain": "admin@ourfirm.com",
  "subject": "Board meeting minutes — March",
  "body": "Attached are the minutes from the March board meeting for approval. Please review the resolutions and confirm the policy updates before the next session.",
  "attachments": []
}
```

**Expected**

| Field | Value |
|---|---|
| `email.label` | `General Governance` |
| `email.identifier` | `null` |
| `email.keyword_hits` | includes `minutes`, `board`, `approval`, `resolution`, `policy` |
| `email.priority_hint` | `High` ← "approval" is a priority keyword |
| `email.monday_board_hint` | `General Governance Intake` |
| `email.sharepoint_folder` | `/Intake/admin@ourfirm.com` |
| `email.needs_review` / `needs_review_text` | `false` / `No` |

---

## 2. Payment / Billing — invoice (priority keyword fires)

**Payload**

```json
{
  "sender_domain": "apex-glass.com",
  "subject": "Invoice #4471 due Net 30",
  "body": "Please remit payment for the storefront glazing scope. Invoice #4471 attached, Net 30 terms, remittance details on page 2.",
  "attachments": []
}
```

**Expected**

| Field | Value |
|---|---|
| `email.label` | `Payment / Billing` |
| `email.identifier` | `null` |
| `email.keyword_hits` | includes `invoice`, `net 30`, `remittance` |
| `email.priority_hint` | `High` ← "invoice" is a priority keyword |
| `email.monday_board_hint` / `monday_group_hint` | `Construction Intake` / `Payment Review` |
| `email.sharepoint_folder` | `/Intake/apex-glass.com` |
| `email.needs_review` | `false` |

---

## 3. Compliance / Legal — government permit

**Payload**

```json
{
  "sender_domain": "city-permits.gov",
  "subject": "Permit approval — site grading",
  "body": "The site grading permit for your project has been approved. The permit certificate and inspection schedule are attached; please post on site before work begins.",
  "attachments": []
}
```

**Expected**

| Field | Value |
|---|---|
| `email.label` | `Compliance / Legal` ← permit *issued by a government office* is Compliance, even though the work is construction (explicit prompt rule) |
| `email.keyword_hits` | includes `permit`, `approval`, `inspection` |
| `email.priority_hint` | `High` ← all three are priority keywords |
| `email.monday_board_hint` | `Compliance Intake` |
| `email.needs_review` | `false` |

---

## 4. Capital / Finance — capital call

**Payload**

```json
{
  "sender_domain": "capital-partners.com",
  "subject": "Q3 capital call notice",
  "body": "This is your Q3 capital call notice. Please review the attached distribution schedule and wire your equity contribution by the due date noted in the notice.",
  "attachments": []
}
```

**Expected**

| Field | Value |
|---|---|
| `email.label` | `Capital / Finance` |
| `email.keyword_hits` | includes `capital call`, `distribution`, `equity`, `wire` |
| `email.priority_hint` | `Normal` |
| `email.monday_board_hint` | `Development Intake` |
| `email.needs_review` | `false` |

---

## 5. Development / Construction — change order with identifier

**Payload**

```json
{
  "sender_domain": "gc-buildwell.com",
  "subject": "Change order #12 — OP-215 slab revision",
  "body": "Change order #12 for OP-215 covers the revised slab depth on Level 1 per the updated structural drawings. No schedule extension is requested; mobilization costs are included.",
  "attachments": []
}
```

**Expected**

| Field | Value |
|---|---|
| `email.label` | `Development / Construction` |
| `email.identifier` | `OP-215` |
| `email.identifier_candidates` | `["OP-215"]` |
| `email.keyword_hits` | includes `change order`, `drawings`, `mobilization` |
| `email.priority_hint` | `High` ← "change order" |
| `email.sharepoint_folder` | `/Deals/01_Active_Deals/OP-215` ← OP- prefix → Deals path |
| `email.monday_board_hint` | `Construction Intake` |
| `email.needs_review` | `false` |

---

## 6. Lease / Occupancy — executed lease with identifier

**Payload**

```json
{
  "sender_domain": "brightleafretail.com",
  "subject": "Executed lease — Maple Crossing Suite 200 (OP-142)",
  "body": "The executed lease for Maple Crossing Suite 200 (OP-142) is attached. Tenant takes occupancy June 1 and rent commences per Section 4 of the agreement.",
  "attachments": []
}
```

**Expected**

| Field | Value |
|---|---|
| `email.label` | `Lease / Occupancy` |
| `email.identifier` | `OP-142` |
| `email.keyword_hits` | includes `lease`, `tenant`, `rent`, `occupancy` |
| `email.priority_hint` | `Normal` |
| `email.sharepoint_folder` | `/Deals/01_Active_Deals/OP-142` |
| `email.monday_board_hint` | `Asset Management Intake` |
| `email.needs_review` | `false` |

---

## 7. Vendor Performance — KPI scorecard with asset identifier

**Payload**

```json
{
  "sender_domain": "assetops@ourfirm.com",
  "subject": "Q3 vendor scorecard — Summit Mechanical (AS-087)",
  "body": "Q3 KPI scorecard for Summit Mechanical at AS-087: 78% on-time work order completion against a 95% target, three SLA breaches on emergency response, 12 escalations. Recommend a performance improvement plan before contract renewal.",
  "attachments": []
}
```

**Expected**

| Field | Value |
|---|---|
| `email.label` | `Vendor Performance` |
| `email.identifier` | `AS-087` |
| `email.keyword_hits` | includes `vendor`, `sla`, `work order`, `kpi` |
| `email.priority_hint` | `Normal` |
| `email.sharepoint_folder` | `/Assets/AS-087` ← AS- prefix → Assets path |
| `email.monday_group_hint` | `Vendor Performance` |
| `email.needs_review` | `false` |

---

## 8. Multi-project detected — two identifiers, review forced

**Payload**

```json
{
  "sender_domain": "gc-buildwell.com",
  "subject": "Invoices for Riverbend (OP-215) and Northgate (OP-142)",
  "body": "Two invoices attached: Invoice #5102 covers the OP-215 slab work and Invoice #5103 covers the OP-142 storefront package. Please process both under Net 30.",
  "attachments": []
}
```

**Expected**

| Field | Value |
|---|---|
| `email.label` | `Payment / Billing` |
| `email.identifier` | one of the two (model picks the most prominent) |
| `email.identifier_candidates` | `["OP-215", "OP-142"]` — both listed |
| `email.multiple_projects_detected` | `true` |
| `email.needs_review` / `needs_review_text` | `true` / `Yes` ← forced even at high confidence |
| `email.review_reasons` | `["multiple_projects_detected"]` |
| `email.priority_hint` | `High` |

This is the case where the intake board should visually flag the item —
the department head decides whether to split it into one item per project.

---

## 9. Low confidence — no signals at all

**Payload**

```json
{
  "sender_domain": "outlook.com",
  "subject": "Following up",
  "body": "Hi, just circling back on the thing we discussed last week. Let me know how you want to proceed and I can send over the rest.",
  "attachments": []
}
```

**Expected**

| Field | Value |
|---|---|
| `email.label` | `General Governance` (the catch-all) |
| `email.confidence` | below `0.60` |
| `email.keyword_hits` | `[]` |
| `email.identifier` | `null` |
| `email.needs_review` / `needs_review_text` | `true` / `Yes` |
| `email.review_reasons` | `["low_confidence"]` |
| `email.sharepoint_folder` | `/Intake/outlook.com` |

> ⚠ Confidence is self-reported and LLMs run overconfident — this case may
> occasionally come back above 0.60 and not trip the flag. If it does, thin
> the email further (subject `"Re:"`, body `"thanks, will do"`), or for a
> demo temporarily raise `CONFIDENCE_THRESHOLD` in `classifier.py`.

---

## Error cases (no LLM call, cost nothing)

### 10. Missing auth → 401

Send any payload **without** the `Authorization` header.

```json
{ "error": "Missing or invalid Authorization header (expected 'Bearer <API_TOKEN>').", "code": "unauthorized" }
```

### 11. Wrong token → 401

`Authorization: Bearer wrong-token` → same shape, code `unauthorized`.

### 12. Missing required field → 422

Omit `sender_domain` from the payload → FastAPI validation error (422),
detail lists the missing field.

---

## Quick reference — what each case proves

| # | Case | Proves |
|---|---|---|
| 1 | Board minutes | catch-all category, holding-path fallback, "approval" priority keyword |
| 2 | Invoice | priority keyword → `High`, Payment group hint |
| 3 | Permit | prompt's permit-vs-construction disambiguation rule |
| 4 | Capital call | Capital/Finance mapping |
| 5 | Change order + OP | identifier → `/Deals/` path |
| 6 | Lease + OP | Lease category + Deals path |
| 7 | Scorecard + AS | identifier → `/Assets/` path, group hint |
| 8 | Two identifiers | `multiple_projects_detected` forces review |
| 9 | Vague email | `low_confidence` review reason |
| 10–12 | Errors | auth + validation without burning quota |
