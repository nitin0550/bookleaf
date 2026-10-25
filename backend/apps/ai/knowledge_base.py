"""
BookLeaf Knowledge Base, split into retrievable sections.

Rather than pasting the whole knowledge base into every prompt, each section is
tagged with the ticket categories it is relevant to. The drafter injects the
tone guidelines (always), the company overview (always, it is short), and only
the sections tagged for the ticket's category. This cuts draft-prompt size by
roughly half to two-thirds compared with sending everything, and it also keeps
the model focused on the one policy that matters for the question.

When the KB grows beyond a few pages, this module is the seam where keyword
tagging would be replaced by embedding retrieval — callers don't change.
"""
from dataclasses import dataclass

from apps.support.models import Category


@dataclass(frozen=True)
class KBSection:
    key: str
    title: str
    body: str
    categories: frozenset[str]


ALWAYS = frozenset({"*"})

COMPANY_OVERVIEW = KBSection(
    key="company_overview",
    title="Company Overview",
    categories=ALWAYS,
    body="""\
- BookLeaf Publishing is a self-publishing company operating in India and the US.
- Packages: Standard Free (no upfront cost) and Bestseller Breakthrough (premium, paid package with marketing and distribution add-ons).
- BookLeaf handles cover design, typesetting, ISBN assignment, printing, distribution and royalty management for authors.
- In-house printing facility and warehouse are in Delhi. Print partners: Repro India and Epitome Books.""",
)

TONE_GUIDELINES = KBSection(
    key="tone_guidelines",
    title="Communication Tone Guidelines",
    categories=ALWAYS,
    body="""\
- Always empathetic and professional. Authors are our partners, not customers to be managed.
- Acknowledge the author's concern before jumping to solutions.
- Be specific: include actual numbers, dates and statuses wherever possible rather than vague reassurances.
- If something is BookLeaf's fault (delayed royalties, ISBN error), own it directly. No corporate deflection.
- If the issue requires escalation or investigation, give a clear timeline ("Our team will look into this and get back to you within 48 hours") rather than open-ended promises.
- Always end with a clear next step for the author and/or the BookLeaf team.""",
)

SECTIONS: list[KBSection] = [
    KBSection(
        key="royalty_policy",
        title="Royalty Policy",
        categories=frozenset({Category.ROYALTY, Category.GENERAL}),
        body="""\
- 80/20 royalty split: 80% of the net profit per book goes to the author, 20% to BookLeaf.
- Net profit = MRP minus printing cost, platform commission (Amazon/Flipkart), and shipping charges.
- Royalties are calculated quarterly and paid within 45 days of the quarter ending.
- Minimum payout threshold: ₹1,000. If accumulated royalties are below this, they roll over to the next quarter.
- Payouts are made via bank transfer to the account linked in the author's dashboard.
- Authors can view a detailed royalty breakdown in their dashboard, showing sales figures per platform.""",
    ),
    KBSection(
        key="isbn_policy",
        title="ISBN Policy",
        categories=frozenset({Category.ISBN, Category.DISTRIBUTION}),
        body="""\
- Every book published through BookLeaf receives a unique ISBN assigned by BookLeaf.
- ISBNs are registered under BookLeaf's publisher imprint. Authors who want an ISBN under their own imprint must obtain it independently.
- An ISBN error reported by an author (duplicate, wrong book linked, mismatch between platform and physical copy) is a high-priority issue and is escalated to the production team immediately. Resolution timeline: 48 hours.""",
    ),
    KBSection(
        key="metadata_updates",
        title="Metadata Updates",
        categories=frozenset({Category.ISBN, Category.GENERAL, Category.DISTRIBUTION}),
        body="""\
- Metadata (description, author bio, keywords, etc.) can be updated after a book is live. Updates are submitted through the dashboard or by emailing the BookLeaf team.
- Changes typically reflect on platforms within 3–5 business days.""",
    ),
    KBSection(
        key="printing_quality",
        title="Printing & Quality",
        categories=frozenset({Category.PRINTING}),
        body="""\
- In-house printing (Delhi) handles most orders. Overflow or specific format requirements go to Repro India or Epitome Books.
- Standard print turnaround: 5–7 business days from order confirmation.
- Quality issues (misprints, binding defects, colour inconsistency, blurry images, misaligned pages): BookLeaf arranges a FREE reprint after verification. The author may need to share photos of the defective copy. Reprint timeline: 5–7 business days once verified.""",
    ),
    KBSection(
        key="distribution",
        title="Distribution & Availability",
        categories=frozenset({Category.DISTRIBUTION, Category.PRODUCTION}),
        body="""\
- Books are listed on Amazon India, Flipkart, Amazon US, Amazon UK, and the BookLeaf Store.
- New listings typically go live within 7–10 business days after publication is complete.
- If a book shows as unavailable ("Currently Unavailable") on a platform, it usually indicates a stock sync issue. BookLeaf's team can trigger a re-sync, which takes 24–48 hours.""",
    ),
    KBSection(
        key="production_stages",
        title="Production Stages",
        categories=frozenset({Category.PRODUCTION}),
        body="""\
- Stages in order: Manuscript Received → Editing (if opted) → Cover Design → Typesetting → Proofreading → ISBN Assignment → Printing → Distribution Setup → Published & Live.
- Authors are updated at each stage via email.
- Delays typically happen at Cover Design (waiting for author approval) and Proofreading (revision rounds). Never blame the author for a delay, even if it is on their side — frame it collaboratively.""",
    ),
]

# Calibration examples from the BookLeaf brief: query → what a good answer does.
EXAMPLES: dict[str, list[tuple[str, str]]] = {
    Category.ROYALTY: [
        (
            "I published my book 4 months ago and still haven't received any royalty. What's going on?",
            "Acknowledge the frustration. Explain the quarterly royalty cycle and 45-day payout window. "
            "Check if their bank details are linked. Provide the specific next payout date. If the payment "
            "is genuinely overdue, escalate with a 48-hour resolution timeline.",
        ),
        (
            "My royalty amount seems too low. I sold 200 copies but only received ₹3,000.",
            "Explain the net profit calculation: MRP minus printing, platform commission, and shipping. "
            "Offer to share a detailed line-by-line royalty breakdown. Don't be defensive — offer transparency.",
        ),
    ],
    Category.ISBN: [
        (
            "My book is showing a different ISBN on Amazon than what's on the physical copy.",
            "Treat as high priority. Acknowledge this is a serious data issue. Confirm you are escalating to "
            "the production team immediately. Provide a 48-hour resolution timeline.",
        ),
    ],
    Category.PRINTING: [
        (
            "I received my author copies and the print quality is terrible. The images are blurry and pages are misaligned.",
            "Apologise sincerely. Ask the author to share photos of the defective copies. Confirm that BookLeaf "
            "will arrange a free reprint once verified. Provide a timeline of 5–7 business days for the reprint.",
        ),
    ],
    Category.DISTRIBUTION: [
        (
            "My book is published but it's showing as 'Currently Unavailable' on Amazon.",
            "Explain that this is typically a stock sync issue. Confirm you're triggering a re-sync with the "
            "distribution team. Set expectation: 24–48 hours for it to go live again.",
        ),
    ],
    Category.PRODUCTION: [
        (
            "It's been 3 weeks and my book is still in typesetting. When will it be done?",
            "Check the actual production status. If it's delayed, be honest about why (e.g., waiting on author "
            "approval for proofs). Provide a specific updated timeline. Don't blame the author even if the delay "
            "is on their side — frame it collaboratively.",
        ),
    ],
    Category.GENERAL: [
        (
            "Can I update the description of my book on Amazon after it's already live?",
            "Yes, metadata updates can be submitted through the dashboard or by emailing the BookLeaf team. "
            "Changes typically reflect on platforms within 3–5 business days.",
        ),
    ],
}


def sections_for(category: str) -> list[KBSection]:
    """Tone + overview + only the policy sections relevant to this category."""
    relevant = [s for s in SECTIONS if category in s.categories]
    return [TONE_GUIDELINES, COMPANY_OVERVIEW, *relevant]


def render_sections(sections: list[KBSection]) -> str:
    return "\n\n".join(f'<kb_section name="{s.title}">\n{s.body}\n</kb_section>' for s in sections)


def render_examples(category: str) -> str:
    items = EXAMPLES.get(category, [])
    return "\n".join(
        f"<example>\n<author_query>{q}</author_query>\n<good_response_does>{a}</good_response_does>\n</example>"
        for q, a in items
    )


def full_kb_char_count() -> int:
    """Size of the whole KB; used to report savings from selective retrieval."""
    everything = [TONE_GUIDELINES, COMPANY_OVERVIEW, *SECTIONS]
    examples = "".join(render_examples(c) for c in EXAMPLES)
    return len(render_sections(everything)) + len(examples)
