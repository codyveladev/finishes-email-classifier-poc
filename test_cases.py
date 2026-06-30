import time
from dotenv import load_dotenv; load_dotenv()
from classifier import classify

REQUEST_INTERVAL_S = 13  # free tier: 5 req/min for gemini-2.5-flash

CASES = [
    ("brightleafretail.com", "Executed lease — Maple Crossing", "",
     "samples/Lease_Agreement_OP-142.pdf", "Lease / Occupancy"),
    ("summitmechanical.com", "HVAC service agreement — Northgate", "",
     "samples/Vendor_Agreement_AS-087.pdf",
     ("Vendor Performance", "Compliance / Legal")),
    ("apex-glass.com", "Invoice #4471 due Net 30", "", None, "Payment / Billing"),
    ("city-permits.gov", "Permit approval — site grading", "", None,
     "Compliance / Legal"),
    ("capital-partners.com", "Q3 capital call notice", "", None,
     "Capital / Finance"),
    ("gc-buildwell.com", "Change order #12 — slab revision", "", None,
     "Development / Construction"),
    ("admin@ourfirm.com", "Board meeting minutes — March", "", None,
     "General Governance"),
]

passed = 0
for i, (domain, subj, body, att, expected) in enumerate(CASES):
    if i > 0:
        time.sleep(REQUEST_INTERVAL_S)
    r = classify(domain, subj, body, att)
    expected_set = expected if isinstance(expected, tuple) else (expected,)
    ok = r["label"] in expected_set
    passed += ok
    flag = " [review]" if r["needs_review"] else ""
    exp_str = " or ".join(expected_set)
    print(f"[{'PASS' if ok else 'FAIL'}] got={r['label']} "
          f"({r['confidence']:.0%}){flag}  expected={exp_str}")
    print(f"        rationale: {r['rationale']}")

print(f"\n{passed}/{len(CASES)} correct")
