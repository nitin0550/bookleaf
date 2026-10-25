"""
Policy-based reply templates used when the AI is unavailable.

They follow the same tone guidelines and pull in real account facts where we
have them, so even in an outage an agent starts from a reasonable, specific
draft instead of a blank box. Placeholders in [square brackets] must be filled
by the agent before sending.
"""
from apps.catalog.royalty import payout_schedule
from apps.support.models import Category


def _first_name(ticket) -> str:
    return (ticket.author.name or "there").split()[0]


def _book_phrase(ticket) -> str:
    return f"“{ticket.book.title}”" if ticket.book_id else "your book"


def template_draft(ticket) -> tuple[str, str]:
    """Returns (reply, suggested_status)."""
    name = _first_name(ticket)
    book = _book_phrase(ticket)
    cat = ticket.category
    schedule = payout_schedule()

    if cat == Category.ROYALTY:
        pending = f"₹{float(ticket.book.royalty_pending):,.0f}" if ticket.book_id else "[pending amount]"
        body = (
            f"Thank you for reaching out about your royalties for {book}, and I completely understand "
            f"how important it is to have clarity here.\n\n"
            f"Royalties at BookLeaf are calculated quarterly and paid within 45 days of each quarter ending, "
            f"by bank transfer to the account linked in your dashboard (minimum payout ₹1,000; smaller amounts "
            f"roll over). Your current pending royalty is {pending}, and the next payout date is "
            f"{schedule.next_payout_date:%d %B %Y}.\n\n"
            f"I'm checking your payout history now and will confirm the details — including a line-by-line "
            f"breakdown if helpful — within 48 hours. [Verify bank details and payout history before sending.]"
        )
        status = "in_progress"
    elif cat == Category.ISBN:
        body = (
            f"Thank you for flagging this — an ISBN or metadata error on {book} is a serious issue, "
            f"and I'm sorry you've run into it.\n\n"
            f"I've escalated this to our production team as a high-priority issue. We'll correct the record "
            f"and confirm back to you within 48 hours."
        )
        status = "in_progress"
    elif cat == Category.PRINTING:
        body = (
            f"I'm really sorry the copies of {book} didn't meet the standard you should expect from us.\n\n"
            f"Could you reply with a few photos of the affected pages or binding? Once we've verified the issue, "
            f"BookLeaf will arrange a free reprint, which takes 5–7 business days."
        )
        status = "in_progress"
    elif cat == Category.DISTRIBUTION:
        body = (
            f"Thank you for letting us know that {book} isn't showing as available — I understand how "
            f"frustrating that is when readers are looking for it.\n\n"
            f"This is usually a stock sync issue between our system and the platform. I've asked our distribution "
            f"team to trigger a re-sync; the listing should be live again within 24–48 hours."
        )
        status = "in_progress"
    elif cat == Category.PRODUCTION:
        stage = ticket.book.production_stage if ticket.book_id else "[current stage]"
        body = (
            f"Thank you for checking in on {book} — I know how eager you are to see it published.\n\n"
            f"Your book is currently at the {stage} stage. I'm confirming the exact timeline with our "
            f"production team and will share a specific date within 48 hours. [Add expected completion date.]"
        )
        status = "in_progress"
    else:
        body = (
            f"Thank you for getting in touch about {book}.\n\n"
            f"[Answer the author's question here.]\n\n"
            f"If you'd like any metadata (such as your description or bio) updated, you can submit it through your "
            f"dashboard or reply here — changes usually reflect on platforms within 3–5 business days."
        )
        status = "resolved"

    reply = f"Hi {name},\n\n{body}\n\nWarm regards,\nBookLeaf Author Support"
    return reply, status
