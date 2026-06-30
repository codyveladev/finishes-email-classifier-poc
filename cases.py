"""Shared test cases — consumed by both the web UI (presets) and test_cases.py."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    name: str                     # display label
    sender_domain: str
    subject: str
    body: str
    attachment: str               # path under samples/, or "" for none
    expected: tuple[str, ...]     # acceptable labels (tuple supports ambiguous cases)


CASES: list[Case] = [
    Case(
        name="Lease — Maple Crossing (OP-142)",
        sender_domain="brightleafretail.com",
        subject="Executed lease — Maple Crossing",
        body="",
        attachment="samples/Lease_Agreement_OP-142.pdf",
        expected=("Lease / Occupancy",),
    ),
    Case(
        name="Vendor — Northgate HVAC (AS-087)",
        sender_domain="summitmechanical.com",
        subject="HVAC service agreement — Northgate",
        body="",
        attachment="samples/Vendor_Agreement_AS-087.pdf",
        expected=("Vendor Performance", "Compliance / Legal"),
    ),
    Case(
        name="Invoice #4471 (no attachment)",
        sender_domain="apex-glass.com",
        subject="Invoice #4471 due Net 30",
        body="",
        attachment="",
        expected=("Payment / Billing",),
    ),
    Case(
        name="Permit approval (no attachment)",
        sender_domain="city-permits.gov",
        subject="Permit approval — site grading",
        body="",
        attachment="",
        expected=("Compliance / Legal",),
    ),
    Case(
        name="Capital call (no attachment)",
        sender_domain="capital-partners.com",
        subject="Q3 capital call notice",
        body="",
        attachment="",
        expected=("Capital / Finance",),
    ),
    Case(
        name="Change order #12 (no attachment)",
        sender_domain="gc-buildwell.com",
        subject="Change order #12 — slab revision",
        body="",
        attachment="",
        expected=("Development / Construction",),
    ),
    Case(
        name="Board minutes (no attachment)",
        sender_domain="admin@ourfirm.com",
        subject="Board meeting minutes — March",
        body="",
        attachment="",
        expected=("General Governance",),
    ),
]
