"""
Deterministic royalty-cycle calculations.

The LLM is never asked to do date arithmetic. We compute the payout schedule
here (quarterly cycle, paid within 45 days of quarter end, ₹1,000 minimum
threshold — straight from the BookLeaf royalty policy) and hand the *results*
to the prompt as facts. This keeps drafted answers specific and correct.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

PAYOUT_WINDOW_DAYS = 45
MIN_PAYOUT_THRESHOLD = Decimal("1000")


def reference_today() -> date:
    """'Today' for business logic; overridable for demos via BOOKLEAF_REFERENCE_DATE."""
    override = getattr(settings, "BOOKLEAF_REFERENCE_DATE", None)
    if override:
        return date.fromisoformat(override)
    return timezone.localdate()


def quarter_bounds(d: date) -> tuple[date, date]:
    q_start_month = 3 * ((d.month - 1) // 3) + 1
    start = date(d.year, q_start_month, 1)
    next_start = date(d.year + (q_start_month == 10), (q_start_month + 3 - 1) % 12 + 1, 1)
    return start, next_start - timedelta(days=1)


def quarter_label(d: date) -> str:
    # Calendar quarters (Jan–Mar = Q1). Labelled with month names to avoid
    # confusion with India's April–March financial year.
    start, end = quarter_bounds(d)
    return f"{start:%b}–{end:%b %Y}"


@dataclass(frozen=True)
class PayoutSchedule:
    today: date
    current_quarter: str
    current_quarter_end: date
    last_closed_quarter: str
    last_closed_quarter_end: date
    last_closed_quarter_payout_deadline: date
    next_payout_date: date
    next_payout_covers: str

    def as_dict(self) -> dict:
        return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in self.__dict__.items()}


def payout_schedule(today: date | None = None) -> PayoutSchedule:
    today = today or reference_today()
    cur_start, cur_end = quarter_bounds(today)
    prev_end = cur_start - timedelta(days=1)
    prev_deadline = prev_end + timedelta(days=PAYOUT_WINDOW_DAYS)

    if today <= prev_deadline:
        next_payout, covers = prev_deadline, quarter_label(prev_end)
    else:
        next_payout, covers = cur_end + timedelta(days=PAYOUT_WINDOW_DAYS), quarter_label(today)

    return PayoutSchedule(
        today=today,
        current_quarter=quarter_label(today),
        current_quarter_end=cur_end,
        last_closed_quarter=quarter_label(prev_end),
        last_closed_quarter_end=prev_end,
        last_closed_quarter_payout_deadline=prev_deadline,
        next_payout_date=next_payout,
        next_payout_covers=covers,
    )


def most_recent_passed_deadline(today: date) -> date:
    """Latest payout deadline (quarter end + 45d) that is already in the past."""
    cur_start, _ = quarter_bounds(today)
    prev_end = cur_start - timedelta(days=1)
    deadline = prev_end + timedelta(days=PAYOUT_WINDOW_DAYS)
    if deadline < today:
        return deadline
    # Go one quarter further back.
    prev_start, _ = quarter_bounds(prev_end)
    prev_prev_end = prev_start - timedelta(days=1)
    return prev_prev_end + timedelta(days=PAYOUT_WINDOW_DAYS)


def book_royalty_flags(book, today: date | None = None) -> dict:
    """Facts about a single book's royalty position, for admins and the AI drafter."""
    today = today or reference_today()
    pending = Decimal(book.royalty_pending or 0)
    flags = {
        "pending_amount": float(pending),
        "below_payout_threshold": Decimal(0) < pending < MIN_PAYOUT_THRESHOLD,
        "never_paid": bool(book.is_published and book.last_royalty_payout_date is None),
        "possibly_overdue": False,
    }
    if not book.is_published or pending <= 0 or not book.publication_date:
        return flags

    deadline = most_recent_passed_deadline(today)
    quarter_paid_by_deadline_end = deadline - timedelta(days=PAYOUT_WINDOW_DAYS)
    sold_before_that_quarter_closed = book.publication_date <= quarter_paid_by_deadline_end
    last_paid = book.last_royalty_payout_date
    # Pending money from a quarter whose payout deadline has passed, with no payout
    # since that deadline's quarter closed, suggests a missed payout worth verifying.
    if (
        pending >= MIN_PAYOUT_THRESHOLD
        and sold_before_that_quarter_closed
        and (last_paid is None or last_paid < quarter_paid_by_deadline_end)
    ):
        flags["possibly_overdue"] = True
    return flags


def author_royalty_summary(author, today: date | None = None) -> dict:
    books = list(author.books.all())
    total_pending = sum((Decimal(b.royalty_pending or 0) for b in books), Decimal(0))
    return {
        "total_earned": float(sum((Decimal(b.total_royalty_earned or 0) for b in books), Decimal(0))),
        "total_paid": float(sum((Decimal(b.royalty_paid or 0) for b in books), Decimal(0))),
        "total_pending": float(total_pending),
        "meets_payout_threshold": total_pending >= MIN_PAYOUT_THRESHOLD,
        "min_payout_threshold": float(MIN_PAYOUT_THRESHOLD),
        "schedule": payout_schedule(today).as_dict(),
    }
