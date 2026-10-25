"""
Deterministic keyword fallback for classification and priority.

Used (a) instantly at ticket creation so every ticket has a usable category and
priority before the AI responds, and (b) permanently if the AI is down,
rate-limited or not configured. It is intentionally simple and transparent;
the queue labels these values as "rules" so staff know to double-check them.
"""
import re
from dataclasses import dataclass

from apps.support.models import Category, Priority

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    Category.ROYALTY: [
        "royalt", "payment", "payout", "paid", "bank", "money", "earning", "amount",
        "statement", "₹", "rs.", "inr", "transfer", "commission",
    ],
    Category.ISBN: ["isbn", "metadata", "barcode", "imprint", "wrong book", "duplicate", "author name spelled"],
    Category.PRINTING: [
        "print", "blurry", "binding", "misprint", "misaligned", "damaged", "defect", "colour",
        "color", "pages missing", "torn", "quality", "reprint", "author copies",
    ],
    Category.DISTRIBUTION: [
        "amazon", "flipkart", "unavailable", "out of stock", "listing", "not showing",
        "can't find", "cannot find", "buy link", "available", "store",
    ],
    Category.PRODUCTION: [
        "typesetting", "cover design", "proofread", "proof", "editing", "production",
        "delay", "still in", "stage", "manuscript", "published yet", "launch date",
    ],
    Category.GENERAL: [
        "bio", "author photo", "profile", "package", "password", "login", "account details",
        "bestseller breakthrough", "contract",
    ],
}

CRITICAL_PATTERNS = [
    r"\blegal\b", r"\blawyer\b", r"\bcopyright\b", r"\bplagiari", r"\bfraud\b",
    r"\bhacked\b", r"(six|6|seven|7|eight|8|nine|9|ten|10|twelve|12)\s+months?\b.*\b(royalt|paid|payment)",
    r"\bno (royalty|payment).*\b(year|months)\b", r"\bsue\b", r"\bconsumer court\b",
]
HIGH_PATTERNS = [
    r"\bisbn\b.*\b(wrong|different|mismatch|duplicate|incorrect)\b",
    r"\b(wrong|different|mismatch|duplicate|incorrect)\b.*\bisbn\b",
    r"\bnot (received|been paid|paid)\b", r"\bhaven'?t (received|been paid|got)\b",
    r"\boverdue\b", r"\bunavailable\b", r"\bout of stock\b", r"\bblurry\b",
    r"\bmisaligned\b", r"\bdefect", r"\bmisprint", r"\burgent\b", r"\bterrible\b",
]
LOW_PATTERNS = [
    r"\bcan i\b", r"\bhow (do|can) i\b", r"\bbio\b", r"\bupdate (my|the) (description|bio|photo)\b",
    r"\bjust (wanted|curious)\b", r"\bquestion about\b", r"\bis it possible\b",
]


@dataclass
class RuleResult:
    category: str
    priority: str
    rationale: str


def classify_by_rules(subject: str, description: str) -> RuleResult:
    text = f"{subject}\n{description}".lower()

    scores = {cat: sum(text.count(k) for k in kws) for cat, kws in CATEGORY_KEYWORDS.items()}
    # ISBN mentions are rare and decisive; weight them up.
    scores[Category.ISBN] *= 2
    best_cat, best_score = max(scores.items(), key=lambda kv: kv[1])
    category = best_cat if best_score > 0 else Category.GENERAL

    if any(re.search(p, text) for p in CRITICAL_PATTERNS):
        priority = Priority.CRITICAL
    elif any(re.search(p, text) for p in HIGH_PATTERNS) or category == Category.ISBN:
        priority = Priority.HIGH
    elif any(re.search(p, text) for p in LOW_PATTERNS) or category == Category.GENERAL:
        priority = Priority.LOW
    else:
        priority = Priority.MEDIUM

    return RuleResult(
        category=category,
        priority=priority,
        rationale="Keyword-based fallback (AI unavailable). Please verify.",
    )
