# Platform Recommendation — Email Intake Automation

**Recommendation: build the intake automation on Power Automate, not Zapier.**

This is not a preference. Testing established that Zapier cannot reliably deliver
email attachments to the classification service, and separately, Zapier is the
wrong fit for a governance system on compliance grounds. Power Automate resolves
both. It carries a licensing cost that Zapier does not, and that cost is
unavoidable for this architecture on either platform.

---

## 1. The decision in one table

| | Zapier | Power Automate |
|---|---|---|
| **Multi-attachment emails** | Not demonstrated. Its file field is documented as accepting "a file object" — singular | Native. Trigger returns all attachments as an array |
| **Where email + attachments travel** | Through Zapier's cloud (third-party, US-hosted) | Stays inside the client's Microsoft 365 tenant |
| **Runs as** | A Zapier service account | The client's own identity, under client licensing |
| **Exchange / SharePoint access** | Third-party connectors | Native, first-party connectors |
| **Audit trail** | Zapier's task history | Microsoft 365 audit log, alongside every other tenant action |
| **Licensing** | ~$30/mo (Starter, for webhook + code steps) | ~$15/user/mo (Premium) — **also required for Monday.com** |
| **Attachment delivery** | **Blocked** (see §3) | Documented and supported |

---

## 2. The compliance argument (the one that matters most)

The Finishes 3.0 governance system exists so that no decision is made outside a
traceable, approved record. Every governed item must be traceable to a source
email.

**Zapier breaks the tenant boundary.** Every email — sender, subject, body, and
every attachment (leases, invoices, permits, capital call notices) — would be
copied out of the client's Microsoft 365 tenant into Zapier's infrastructure and
retained in its task history. For a system whose entire premise is controlled,
auditable handling of sensitive property documents, routing those documents
through an unrelated third-party SaaS is difficult to defend to a compliance
reviewer.

**Power Automate does not.** The flow runs inside the client's own tenant, under
the client's own identity and licensing. Email and attachments never leave
Microsoft 365 except for the single classification call. Every run appears in the
Microsoft 365 audit log next to every other action in the tenant.

This alone is sufficient reason. The attachment finding below is what makes it
non-negotiable.

---

## 3. The technical finding: Zapier cannot deliver the attachments

This was established through direct testing, not assumed.

**What Zapier gives you.** Its Outlook trigger does not return the attachment.
It returns a placeholder token:

```
hydrate|||.eJytUN1umzAUfhdfJxGg0kCkSnNCoFSQhJasa26QMQ54gE3ALLAq...|||hydrate
```

Think of it as a claim ticket rather than the file. Only certain Zapier actions
will redeem it, and they decide the terms.

**What we tried:**

| Attempt | Result |
|---|---|
| Fetch the token in a Code step | Code steps never redeem the ticket — they receive the literal token text. No file to fetch |
| Webhook "Custom Request" with the file in the data payload | Token forwarded as plain text. Service rejected it: *"Expected UploadFile, received: str"* |
| Webhook "POST" with the file in the data payload | Same failure |
| Webhook "POST" using its dedicated **File** field | The only hydrating path — but documented as *"A file **object**"*, singular |

**Why this is fatal, not inconvenient.** A real intake email carries several
documents. Our own test email carried two: a lease (`OP-142`) and a permit
approval (`OP-118`) — two different projects in one message. Detecting exactly
that situation and flagging it for a human is a core feature of the classifier.
A platform that can forward one file at a time either drops attachments silently
or classifies each in isolation, which destroys the ability to see that an email
spans two projects.

**What Power Automate gives you.** Its Outlook trigger returns every attachment
in one array, each carrying `contentBytes` — the actual file content, already
encoded and ready to send. No tokens, no redemption step, no per-file limit. One
action reshapes the array; one call sends the whole email for classification.

*Confidence note: the Zapier limitations above were reproduced directly. The
Power Automate behaviour is documented connector schema rather than something we
have yet run end-to-end — it should be confirmed during the first build sprint,
though the failure mode Zapier exhibits does not exist there by design.*

---

## 4. Licensing — the honest numbers

**Power Automate Premium: ~$15/user/month.** Required because the flow calls two
services outside Microsoft: the classification API and Monday.com. Microsoft
gates external calls behind this licence. There is no free configuration of this
architecture — this cost was implicit in the original design, which specified
Power Automate and Azure Functions from the outset.

**Zapier is not free either.** The Starter plan (~$30/month) is the minimum for
the webhook and code steps this would need — and it still cannot deliver the
attachments.

**Recommended path:** Power Automate Premium includes a **90-day trial**. That is
enough to build and demonstrate the complete flow at no cost. Nothing built
during the trial is discarded — the licences are required for production either
way.

---

## 5. What has already been proven

The classification service is **built, deployed, and working.** It is independent
of this platform decision — Zapier, Power Automate, or anything else calls the
same API and receives the same result.

Demonstrated:

- Classifies an email into one of the seven governance categories, with a
  one-sentence rationale for every decision
- Extracts project and asset identifiers (`OP-###`, `AS-###`) from the subject,
  body, and the text inside PDF and Word attachments
- Attributes each identifier to the specific file it came from — so a reviewer
  can see which document belongs to which project
- Flags multi-project emails for human review automatically
- Flags low-confidence classifications for human review rather than guessing
- Returns the suggested SharePoint folder, Monday board, group, and priority

The remaining work is orchestration: capturing the email, filing the attachment,
and creating the Monday item. That is the part requiring the platform decision.

---

## 6. Recommendation

1. **Build on Power Automate.** The tenant-boundary argument is decisive for a
   governance system; the attachment finding removes Zapier as an option
   regardless.
2. **Start the 90-day Premium trial** to build and demonstrate the flow at no
   cost.
3. **Budget Power Automate Premium licences** for the production rollout. This is
   an unavoidable cost of any architecture where Microsoft-hosted workflows talk
   to Monday.com.
4. **Retire the Zapier account** for this project. It remains fine for
   low-sensitivity internal automation; it is not suitable for governed
   documents.
