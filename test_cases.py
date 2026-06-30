"""Phase 2 test runner. Runs ONE case by default to keep free-tier quota happy;
set RUN_ALL=1 to run every case in cases.CASES with a 13s delay between calls."""

import os
import time
from dotenv import load_dotenv; load_dotenv()

from classifier import classify
from cases import CASES

REQUEST_INTERVAL_S = 13  # free tier: 5 req/min for the Flash models

run_all = os.environ.get("RUN_ALL") == "1"
cases_to_run = CASES if run_all else CASES[:1]

passed = 0
for i, case in enumerate(cases_to_run):
    if i > 0:
        time.sleep(REQUEST_INTERVAL_S)
    r = classify(case.sender_domain, case.subject, case.body, case.attachment or None)
    ok = r["label"] in case.expected
    passed += ok
    flag = " [review]" if r["needs_review"] else ""
    exp_str = " or ".join(case.expected)
    print(f"[{'PASS' if ok else 'FAIL'}] {case.name}")
    print(f"        got={r['label']} ({r['confidence']:.0%}){flag}  expected={exp_str}")
    print(f"        identifier={r['identifier'] or '(none)'}")
    print(f"        rationale: {r['rationale']}")

print(f"\n{passed}/{len(cases_to_run)} correct"
      f"{'' if run_all else '  (set RUN_ALL=1 to run all 7)'}")
