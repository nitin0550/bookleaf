"""
Builds the compact, factual context the model sees about an author and ticket.

Token budget rules (cost awareness):
* Only the book the ticket is about is described in detail. For account-level
  tickets we include a one-line summary per book instead.
* The conversation is capped to the most recent messages, each truncated.
  Internal staff notes are never sent (they may contain sensitive remarks and
  are not needed to draft an author-facing reply).
* All numbers/dates are pre-computed in Python (see catalog.royalty) so the
  model copies facts rather than calculating them.
"""
from apps.catalog.royalty import author_royalty_summary, book_royalty_flags, payout_schedule, reference_today

MAX_DESCRIPTION_CHARS = 3000
MAX_MESSAGE_CHARS = 1200
MAX_THREAD_MESSAGES = 6


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 20].rstrip() + " …[truncated]"


def _money(value) -> str:
    return "—" if value is None else f"₹{float(value):,.0f}"


def book_facts(book, *, detailed: bool) -> str:
    if not detailed:
        return (
            f"- {book.title} ({book.book_id}): {book.status}; sold {book.total_copies_sold}; "
            f"pending royalty {_money(book.royalty_pending)}"
        )
    flags = book_royalty_flags(book)
    lines = [
        f"Title: {book.title} ({book.book_id})",
        f"ISBN: {book.isbn or 'not yet assigned'}",
        f"Genre: {book.genre}",
        f"Status: {book.status}",
    ]
    if book.is_published:
        lines += [
            f"Publication date: {book.publication_date.isoformat() if book.publication_date else 'unknown'}",
            f"MRP: {_money(book.mrp)}; author royalty per copy: {_money(book.author_royalty_per_copy)}",
            f"Copies sold: {book.total_copies_sold}",
            f"Royalty earned: {_money(book.total_royalty_earned)}; paid: {_money(book.royalty_paid)}; "
            f"pending: {_money(book.royalty_pending)}",
            "Last royalty payout: "
            + (book.last_royalty_payout_date.isoformat() if book.last_royalty_payout_date else "never paid yet"),
            f"Printed by: {book.print_partner or 'n/a'}",
            f"Listed on: {', '.join(book.available_on) or 'not listed yet'}",
        ]
        if flags["below_payout_threshold"]:
            lines.append("Note: pending royalty for this book alone is below the ₹1,000 payout threshold.")
        if flags["possibly_overdue"]:
            lines.append(
                "Note: a payout deadline has passed with this royalty still pending — this may be an "
                "overdue payment on BookLeaf's side; acknowledge and escalate (48h)."
            )
    else:
        progress = book.production_progress
        lines.append(
            f"Production stage: {progress['stage']} (step {progress['step']} of {progress['total_steps']}); "
            "no sales or royalties yet because the book is not published."
        )
    return "\n".join(lines)


def author_facts(ticket) -> str:
    author = ticket.author
    summary = author_royalty_summary(author)
    schedule = payout_schedule()
    books = list(author.books.all())

    parts = [
        f"Author: {author.name} ({author.author_id}), {author.city}; with BookLeaf since "
        f"{author.joined_date.isoformat() if author.joined_date else 'unknown'}",
        f"Payout bank account linked: {'yes' if author.bank_account_linked else 'NO — ask them to add it'}",
        f"Account totals: earned {_money(summary['total_earned'])}, paid {_money(summary['total_paid'])}, "
        f"pending {_money(summary['total_pending'])} across {len(books)} book(s)"
        + ("" if summary["meets_payout_threshold"] or not summary["total_pending"]
           else " (below the ₹1,000 payout threshold, will roll over)"),
        f"Today: {schedule.today.isoformat()}. Royalty cycle: next payout date is "
        f"{schedule.next_payout_date.isoformat()} (covers {schedule.next_payout_covers}).",
    ]

    if ticket.book_id:
        parts.append("Book this ticket is about:\n" + book_facts(ticket.book, detailed=True))
        others = [b for b in books if b.pk != ticket.book_id]
        if others:
            parts.append("Other books:\n" + "\n".join(book_facts(b, detailed=False) for b in others))
    else:
        parts.append("Ticket is account-level (no specific book). Books:\n"
                     + "\n".join(book_facts(b, detailed=False) for b in books))
    return "\n\n".join(parts)


def thread_text(ticket) -> str:
    lines = [
        f"[Author, {ticket.created_at:%Y-%m-%d}] Subject: {ticket.subject}\n"
        f"{_truncate(ticket.description, MAX_DESCRIPTION_CHARS)}"
    ]
    messages = list(ticket.messages.select_related("sender").order_by("-created_at")[:MAX_THREAD_MESSAGES])
    omitted = ticket.messages.count() - len(messages)
    if omitted > 0:
        lines.append(f"[{omitted} earlier message(s) omitted]")
    for m in reversed(messages):
        who = "Author" if m.sender_role == "author" else "BookLeaf Support"
        lines.append(f"[{who}, {m.created_at:%Y-%m-%d}]\n{_truncate(m.body, MAX_MESSAGE_CHARS)}")
    return "\n\n".join(lines)


def classification_hints(ticket) -> str:
    """Tiny factual hints that legitimately change priority (e.g. a royalty really is unpaid)."""
    hints = []
    if ticket.book_id:
        b = ticket.book
        hints.append(f"Book status: {b.status}")
        if b.is_published:
            flags = book_royalty_flags(b)
            if flags["never_paid"]:
                hints.append("No royalty has ever been paid for this book")
            if flags["possibly_overdue"]:
                hints.append("Pending royalty past its payout deadline (possibly overdue)")
            days = b.days_since_publication(reference_today())
            if days is not None:
                hints.append(f"Published {days} days ago")
    else:
        hints.append("Account-level query (no specific book selected)")
    return "; ".join(hints)
