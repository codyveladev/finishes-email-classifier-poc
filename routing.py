"""Routing hints — pure functions of classifier output.

Given a category label, an identifier, keyword hits, and the sender domain,
compute (a) where the attachment would land in SharePoint once approved,
(b) which Monday intake board + group the item should target, and
(c) whether the keyword hits warrant a priority flag.

Everything here is deterministic — no external calls. Downstream
orchestrators (Power Automate / Zapier / Monday automations) consume the
hints; a human still confirms them at intake-board approval time.
"""

from typing import Optional


# Category → (board, group). Group is optional. Illustrative names —
# real workspace board names get filled in when deploying to the client.
_MONDAY_HINTS: dict[str, tuple[str, Optional[str]]] = {
    "Development / Construction": ("Construction Intake", None),
    "Payment / Billing":          ("Construction Intake", "Payment Review"),
    "Lease / Occupancy":          ("Asset Management Intake", None),
    "Compliance / Legal":         ("Compliance Intake", None),
    "Capital / Finance":          ("Development Intake", None),
    "Vendor Performance":         ("Construction Intake", "Vendor Performance"),
    "General Governance":         ("General Governance Intake", None),
}

# Keywords that promote an item to high priority (from Exhibit A step 5).
_PRIORITY_KEYWORDS: frozenset[str] = frozenset({
    "invoice",
    "pay application",
    "change order",
    "survey",
    "inspection",
    "approval",
    "permit",
})


def sharepoint_folder_for(identifier: Optional[str], sender_domain: str) -> str:
    """Return the SharePoint path suggestion.

    Deals go under /Deals/01_Active_Deals/OP-###.
    Assets go under /Assets/AS-###.
    Unresolved identifiers stay in a holding location keyed by sender domain —
    the human sets the identifier at intake approval, and a Monday automation
    then moves the file to its final home.
    """
    if identifier:
        up = identifier.upper()
        if up.startswith("OP-"):
            return f"/Deals/01_Active_Deals/{up}"
        if up.startswith("AS-"):
            return f"/Assets/{up}"
    # Fall through: unresolved identifier → holding path.
    safe_domain = (sender_domain or "unknown").strip().lower() or "unknown"
    return f"/Intake/{safe_domain}"


def monday_hints_for(label: str) -> tuple[str, Optional[str]]:
    """Return (board_hint, group_hint) for the category. Unknown labels fall
    back to General Governance so downstream never has to handle nulls here."""
    return _MONDAY_HINTS.get(label, _MONDAY_HINTS["General Governance"])


def priority_for(keyword_hits: list[str]) -> str:
    """Return 'high' if any hit is a priority keyword, else 'normal'."""
    for hit in keyword_hits:
        if hit.lower() in _PRIORITY_KEYWORDS:
            return "high"
    return "normal"


def compute_routing(
    label: str,
    identifier: Optional[str],
    keyword_hits: list[str],
    sender_domain: str,
) -> dict:
    """Assemble the full routing block that goes into each attachment result."""
    board, group = monday_hints_for(label)
    return {
        "sharepoint_folder": sharepoint_folder_for(identifier, sender_domain),
        "monday_board_hint": board,
        "monday_group_hint": group,
        "priority_hint": priority_for(keyword_hits),
    }
