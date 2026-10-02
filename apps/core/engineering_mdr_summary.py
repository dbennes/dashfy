"""MDR Document Status summaries shared by the chart and discipline table."""
from collections import Counter


MDR_STATUSES = (
    ("ifr-new", "MABU WORKING UNDER FOE - IFR 1 (New)"),
    ("ifa-new", "MABU WORKING UNDER FOE - IFA 1 (New)"),
    ("afc-new", "MABU WORKING UNDER FOE - AFC/AFU 1 (New)"),
    ("ifi-new", "MABU WORKING UNDER FOE - IFI (New)"),
    ("final-issuance", "MABU WORKING UNDER FOE - AFC/AFU FOR FINAL ISSUANCE"),
    ("cpy-review", "UNDER CPY REVIEW (FOE)"),
    ("finalized-foe", "DOCUMENT FINALIZED UNDER FOE"),
    ("finalized-ded", "DOCUMENT FINALIZED UNDER DED"),
)

MDR_SHORT_LABELS = {
    "ifr-new": "IFR (FOE)",
    "ifa-new": "IFA (FOE)",
    "afc-new": "AFC/AFU (FOE)",
    "ifi-new": "IFI (FOE)",
    "final-issuance": "Final issuance (FOE)",
    "cpy-review": "CPY review (FOE)",
    "finalized-foe": "Finalized FOE",
    "finalized-ded": "Finalized DED",
}


def _normalized(value):
    return " ".join(str(value or "").upper().split())


def is_fabrication_installation(doc):
    return _normalized(doc.get("engineering_category")) in {"CAT 0/1", "CAT 2"}


def mdr_scope_summaries(documents, discipline_order):
    labels = {_normalized(label): label for _tone, label in MDR_STATUSES}

    def status(doc):
        value = _normalized(doc.get("document_status_original"))
        return labels.get(value, value or "UNCLASSIFIED")

    extra_statuses = sorted({status(doc) for doc in documents} - set(labels.values()))
    columns = [*MDR_STATUSES, *(("unclassified", label) for label in extra_statuses)]
    category_available = all("engineering_category" in doc for doc in documents)
    result = []
    for key, label, docs in (
        ("overall", "Overall", documents),
        ("fabrication_installation", "Fabrication & Installation (CAT 0/1 & 2)",
         [doc for doc in documents if is_fabrication_installation(doc)]),
    ):
        total = len(docs)
        counts = Counter(status(doc) for doc in docs)

        def pct(value):
            return 100 * value / total if total else 0

        status_rows = [
            {"tone": tone, "label": name, "short_label": MDR_SHORT_LABELS.get(tone, name),
             "value": counts[name], "pct": pct(counts[name]), "pct_css": f"{pct(counts[name]):.4f}"}
            for tone, name in columns
        ]
        discipline_rows = []
        for discipline in discipline_order:
            group = [doc for doc in docs if doc.get("discipline") == discipline]
            # Retain disciplines in both views for easy comparison.
            if not any(doc.get("discipline") == discipline for doc in documents):
                continue
            group_counts = Counter(status(doc) for doc in group)
            discipline_rows.append({
                "discipline": discipline, "total": len(group), "pct": pct(len(group)),
                "status_cells": [{"value": group_counts[name], "tone": tone, "label": name} for tone, name in columns],
            })
        finalized = counts["DOCUMENT FINALIZED UNDER FOE"] + counts["DOCUMENT FINALIZED UNDER DED"]
        cpy_review = counts["UNDER CPY REVIEW (FOE)"]
        working = sum(count for name, count in counts.items() if name.startswith("MABU WORKING UNDER FOE -"))
        result.append({
            "key": key, "label": label, "total": total, "total_pct": 100 if total else 0,
            "available": key == "overall" or category_available,
            "status_rows": status_rows, "discipline_rows": discipline_rows,
            "finalized": finalized, "finalized_pct": pct(finalized),
            "cpy_review": cpy_review, "cpy_review_pct": pct(cpy_review),
            "working": working, "working_pct": pct(working),
        })
    return result
