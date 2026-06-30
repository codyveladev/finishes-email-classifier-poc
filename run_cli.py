from dotenv import load_dotenv; load_dotenv()
from classifier import classify


if __name__ == "__main__":
    r = classify(
        sender_domain="brightleafretail.com",
        subject="Executed lease — Maple Crossing Suite 200",
        body="Signed lease attached for your records.",
        attachment_path="samples/Lease_Agreement_OP-142.pdf",
    )
    flag = "  [needs review]" if r["needs_review"] else ""
    print(f"{r['label']}  ({r['confidence']:.0%}){flag}")
    print(r["rationale"])
    print(f"identifier: {r['identifier'] or '(none)'} — {r['identifier_rationale']}")
    print("candidates:", r["identifier_candidates"])
    print("hits:", r["keyword_hits"])
