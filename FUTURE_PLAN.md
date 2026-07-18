# FUTURE_PLAN.md — Production Roadmap

Where this goes after the POC: multiple models, real API-key management, a
durable audit trail, an Azure home, and a move into the Finishes organization.

This is a plan, not a build log. Each section states the goal, a concrete
design, and the honest traps. Nothing here is built yet.

---

## 0. Guiding principle

This is a **governance** system. That reframes three things from "nice to have"
into "required":

- **Every classification must be traceable** — who asked, when, what came back,
  which model decided. That's the audit log, and it's a first-class feature, not
  telemetry.
- **Secrets never sit in plaintext** — API keys hashed at rest, model
  credentials in Key Vault.
- **The model that reads the documents is part of the compliance story** — see
  §2 and §5. Where document text goes matters.

---

## 1. Model selection

### Goal

Stop hardcoding `MODEL = "gemini-2.5-flash"`. Support multiple models across
providers (Gemini today; Azure OpenAI for in-tenant residency; Claude as an
option), selectable per-deployment and optionally per-request.

### Design — a provider abstraction

The classifier already isolates the LLM call to one function. Formalize it:

```
providers/
  base.py          # Protocol: classify(signal: str) -> Classification
  gemini.py        # wraps google-genai
  azure_openai.py  # wraps openai with Azure endpoint
  anthropic.py     # wraps anthropic (optional)
```

A registry maps a stable model id to a provider + that provider's model name:

```python
MODEL_REGISTRY = {
    "gemini-2.5-flash":  ("gemini", "gemini-2.5-flash"),
    "gemini-2.5-pro":    ("gemini", "gemini-2.5-pro"),
    "azure-gpt-4o":      ("azure_openai", "gpt-4o"),
    "claude-sonnet":     ("anthropic", "claude-sonnet-4-5"),
}
```

- `classify()` takes an optional `model` argument; falls back to a configured
  default.
- Each provider reads **its own** credential from config/Key Vault — the
  registry never holds secrets.
- The pydantic `Classification` schema stays identical across providers, so the
  response shape never changes. Only the call site differs.

### Per-request selection

The API request may include `"model": "azure-gpt-4o"`. Validate it against:
1. the registry (is it a known model?), and
2. the calling key's `allowed_models` (is this consumer permitted to use it?).

Reject unknown/unpermitted models with a `400 model_not_allowed`.

### Traps

- **Structured output differs by provider.** Gemini uses `response_schema`;
  Azure OpenAI uses tool-calling or JSON mode; Claude uses tool-use. Each
  provider adapter owns that translation and must return the same
  `Classification` object.
- **Confidence isn't comparable across models.** A 0.9 from Gemini and a 0.9
  from GPT-4o aren't the same. If we ever tune the `needs_review` threshold,
  it may need to be per-model.
- **Re-verify accuracy on model swap.** The seven-category test set
  (`test_cases.py`) should be re-run whenever the default model changes, and
  the result recorded.

---

## 2. API-key management

### Goal

Replace the single shared `API_TOKEN` with per-consumer keys — one per Power
Automate flow, per client, per environment — so usage is attributable,
revocable, and scoped.

### Data model

```
api_keys
  id             INTEGER PRIMARY KEY
  name           TEXT       -- "Construction PA flow", "Client Acme prod"
  key_hash       TEXT       -- sha256(token); NEVER store the token itself
  key_prefix     TEXT       -- first 8 chars, for identifying a key in logs/UI
  active         BOOLEAN    -- soft revoke
  allowed_models TEXT       -- JSON array, or NULL = all models
  created_at     TIMESTAMP
  last_used_at   TIMESTAMP
```

### How it works

- **Generation:** create a token (`secrets.token_urlsafe(32)`), show it **once**,
  store only `sha256(token)` and the prefix. Same discipline as password
  hashing — a leaked database yields no usable keys.
- **Verification:** on each request, hash the presented bearer token, look it up,
  check `active`, update `last_used_at`. Replaces the current single-string
  compare in `dependencies.py`.
- **Revocation:** flip `active = false`. Instant, no redeploy.
- **Scoping:** `allowed_models` gates §1's per-request selection.

### Traps

- **Timing-safe compare** on the hash (`hmac.compare_digest`) even though it's
  hashed — habit worth keeping.
- **Bootstrapping:** the very first key has to be created via a CLI/admin path,
  not the API (chicken-and-egg). A small `manage_keys.py` script.
- **Caching:** a per-request DB lookup on the hot path is fine at POC volume;
  add a short in-memory TTL cache if it ever matters.

---

## 3. Audit log

### Goal

An append-only record of every classification: who asked, what they sent
(metadata, not content), what came back, and how long it took. This is the
traceability backbone the governance system requires.

### Data model

```
audit_log
  id                    INTEGER PRIMARY KEY
  timestamp             TIMESTAMP
  api_key_id            INTEGER  -- FK to api_keys; WHO
  sender_domain         TEXT
  subject               TEXT
  attachment_count      INTEGER
  attachment_names      TEXT     -- JSON array
  attachment_hashes     TEXT     -- JSON array of sha256 per file
  model                 TEXT     -- which model decided
  label                 TEXT
  confidence            REAL
  identifier            TEXT
  identifier_candidates TEXT     -- JSON array
  needs_review          BOOLEAN
  review_reasons        TEXT     -- JSON array
  latency_ms            INTEGER
  status                TEXT     -- "ok" | "error"
  error_code            TEXT     -- null on success
```

### What we log — and what we deliberately don't

- **Log:** the classification decision, the inputs' *metadata*, and the
  attachment **hashes** (`sha256` per file). Hashes give integrity + dedup
  without storing the documents.
- **Don't log:** attachment bytes or extracted document text. It's sensitive,
  it's large, and the file already lives in SharePoint. The audit row points at
  it by hash, not by copy.
- **Subject/body:** subject yes (it's the item name anyway); full body is a
  policy call — probably a length-capped snippet, or omit and rely on the
  SharePoint/Monday link.

### Storage — and why SQLite alone is a trap here

SQLite is perfect for **developing** the schema and the code. But for the audit
log specifically, App Service has an **ephemeral filesystem** — a restart or
scale event wipes a local `.db` file. An audit log you can lose on restart isn't
an audit log.

Progression:

| Stage | Keys + audit storage |
|---|---|
| Local / POC | SQLite (`sqlite3`, stdlib) — prototype the schema and queries |
| Azure, single instance | SQLite on a **mounted Azure Files** share (survives restarts) — quick bridge |
| Production | **Azure Database for PostgreSQL (Flexible Server)** for keys + audit, OR **Azure Table Storage** for the append-heavy audit log and Postgres for keys |

Recommendation: build against a thin data-access layer (`db.py`) so the engine
is swappable. Prototype on SQLite, land on Postgres. Don't let SQLite calls
leak into route handlers.

### Bonus the audit log unlocks

- **Idempotency** (a known gap): `attachment_hashes` + `sender_domain` is exactly
  the dedup key from the intake flow. The audit table can back it.
- **Metrics:** triage rate, per-model accuracy drift, per-key volume — all
  queries against this table.

---

## 4. Putting 1–3 together — request lifecycle

```
request → verify_bearer (hash lookup, active check, touch last_used_at)
        → resolve model (request override ∩ key.allowed_models ∩ registry)
        → run_classification (provider adapter)
        → write audit_log row (who, inputs metadata, decision, latency)
        → return response
```

`config.py` grows a `DATABASE_URL`; `dependencies.py` swaps its string-compare
for a DB-backed check; a new `audit.py` writes rows; `service.py` picks up the
resolved model. The response contract to Power Automate/Zapier **does not
change** — this is all internal.

---

## 5. Azure deployment

Sequenced so each step is independently shippable.

### Step 1 — App Service (lift and shift)

- **Azure App Service, Linux, Python 3.12, Basic B1** (~$13/mo, no cold start).
- Startup: `gunicorn app:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000`
- App settings: `GEMINI_API_KEY`, `API_TOKEN`, `SCM_DO_BUILD_DURING_DEPLOYMENT=true`.
- Result: same service, in-tenant, no more Render cold starts.

### Step 2 — Key Vault + managed identity

- System-assigned managed identity on the Web App.
- Grant it **Key Vault Secrets User** on a new vault.
- App settings reference secrets: `@Microsoft.KeyVault(SecretUri=...)`.
- Credentials leave plaintext config entirely.

### Step 3 — Database

- **Azure Database for PostgreSQL (Flexible Server)**, smallest burstable tier.
- Holds `api_keys` and `audit_log` (§2, §3).
- Connection string in Key Vault; accessed via managed identity where possible.

### Step 4 — Observability

- **Application Insights** for operational telemetry (latency, error rates,
  dependency calls to the model provider). Distinct from the governance audit
  log — Insights is for running the service; `audit_log` is for the governance
  record.

### Step 5 — Azure OpenAI (close the residency gap)

- The one hole in the tenant-boundary argument: even hosted in Azure, Gemini
  sends document text to Google. Register an **Azure OpenAI** resource, add the
  `azure_openai` provider (§1), make it the default.
- Contained change — categories, identifier extraction, routing all unchanged.
- Re-run the accuracy suite; record the result.

### Cost sketch (production)

| Item | ~ / month |
|---|---|
| App Service Basic B1 | $13 |
| PostgreSQL Flexible (burstable) | $15–25 |
| Key Vault | negligible |
| Application Insights | usage-based, low |
| Azure OpenAI | per-token, fractions of a cent per email |

---

## 6. Move to the Finishes organization

Currently `codyveladev/finishes-email-classifier-poc` (personal). Production
belongs in the org.

### Decision: transfer vs. fresh repo

**Transfer** (recommended). GitHub's repo-transfer preserves the full history,
all the PRs, and the hard-won commit messages (the binary-encoding saga alone is
worth keeping). Settings → General → Transfer ownership → `finishes-org`.

A fresh repo loses all of that for no real gain.

### After transfer

- **Rename** off "poc" — pick the real name (candidates discussed separately;
  `foreman`, `bindery`, `placemark`…). Update the README, and Power Automate's
  HTTP URI if the deploy URL changes.
- **Branch protection** on `main`: require PR + passing checks, no direct pushes.
- **CI**: GitHub Actions running `test_api.py` (with `SKIP_LIVE=1` so CI needs no
  Gemini key) on every PR.
- **Secrets**: repo/org Actions secrets for deployment; never the model keys
  themselves (those live in Key Vault).
- **Access**: give the Finishes team read/write per their model; remove the
  dependence on a personal account.
- **CODEOWNERS + a short CONTRIBUTING** if more than one person will touch it.

### Traps

- **Update every hardcoded URL** after rename/redeploy — Power Automate HTTP
  action, README badges, any docs referencing the Render URL.
- **The API_TOKEN in this chat is burned** — it's been pasted in plaintext
  repeatedly. Rotate it as part of the move (and it becomes moot once §2 lands).
- **Render teardown**: once Azure is live and Power Automate points at it,
  decommission the Render service so there aren't two endpoints.

---

## 7. Suggested sequence

1. **API keys + audit on SQLite, locally** (§2, §3) — highest-value, and it
   makes the service defensible as a governance component. Build against a
   swappable `db.py`.
2. **Move to the Finishes org** (§6) — do this before more people touch it, and
   rotate the token on the way.
3. **Azure App Service + Key Vault** (§5 steps 1–2) — get off Render, secrets
   secured.
4. **Postgres** (§5 step 3) — migrate keys + audit off SQLite before real volume.
5. **Model selection** (§1) — now that keys can scope it.
6. **Azure OpenAI default** (§5 step 5) — closes the residency gap for the
   compliance review.

1–2 are cheap and high-leverage. 3–6 are the production hardening, in dependency
order.
