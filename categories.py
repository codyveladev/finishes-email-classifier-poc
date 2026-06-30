"""Category labels and keyword cue map for the classifier."""

LABELS = [
    "Development / Construction",
    "Payment / Billing",
    "Lease / Occupancy",
    "Compliance / Legal",
    "Capital / Finance",
    "Vendor Performance",
    "General Governance",
]

CUES: dict[str, list[str]] = {
    "Development / Construction": [
        "change order", "rfi", "submittal", "punch list", "contractor",
        "drawings", "mobilization", "site work",
    ],
    "Payment / Billing": [
        "invoice", "pay application", "remittance", "statement", "past due",
        "billing", "receipt", "wire", "net 30",
    ],
    "Lease / Occupancy": [
        "lease", "tenant", "landlord", "premises", "rent", "occupancy",
        "estoppel", "cam", "renewal", "vacancy",
    ],
    "Compliance / Legal": [
        "permit", "license", "compliance", "violation", "zoning", "attorney",
        "litigation", "nda", "certificate of insurance",
    ],
    "Capital / Finance": [
        "capital call", "equity", "loan", "debt", "refinance", "draw",
        "budget", "pro forma", "distribution", "investor",
    ],
    "Vendor Performance": [
        "vendor", "supplier", "service agreement", "sla", "scope of work",
        "maintenance", "work order", "kpi",
    ],
    "General Governance": [
        "minutes", "board", "policy", "memo", "approval", "resolution",
        "correspondence",
    ],
}


def keyword_hits(text: str) -> list[str]:
    """Return every cue keyword found in the lowercased text, deduped, order preserved."""
    haystack = text.lower()
    seen: set[str] = set()
    hits: list[str] = []
    for cues in CUES.values():
        for cue in cues:
            if cue in haystack and cue not in seen:
                seen.add(cue)
                hits.append(cue)
    return hits
