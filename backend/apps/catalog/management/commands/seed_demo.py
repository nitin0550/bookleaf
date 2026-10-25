"""
Seed the database from bookleaf_sample_data.json (idempotent).

    python manage.py seed_demo                  # authors, books, staff accounts
    python manage.py seed_demo --demo-tickets   # + a few realistic sample tickets
"""
import json
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import Author, Book

DEFAULT_DATA = settings.REPO_ROOT / "data" / "bookleaf_sample_data.json"

STAFF = [
    ("admin@bookleaf.com", "Aisha Verma"),
    ("support@bookleaf.com", "Rahul Mehta"),
]

# (author_id, book_id or None, subject, description, hours_ago, staff_reply or None, status)
DEMO_TICKETS = [
    ("AUTH003", "BK005", "No royalty received since publication",
     "Hi, my book Between Two Temples was published in July 2024 and I have still not received a single "
     "rupee in royalty. My dashboard shows sales but the paid amount is zero. This is really disappointing "
     "— can someone tell me what is going on?", 30, None, "open"),
    ("AUTH002", "BK003", "Amazon shows a different ISBN than my printed book",
     "The ISBN printed on the back cover of Code & Karma doesn't match the one shown on the Amazon India "
     "listing. Readers are getting confused and one bookstore said they couldn't order it.", 20, None, "open"),
    ("AUTH004", "BK006", "Author copies have blurry images and misaligned pages",
     "I just received my 20 author copies of Debugging Life. The diagrams in chapter 3 are blurry and "
     "several pages are misaligned. I was planning to hand these out at a launch event next week.",
     8, None, "open"),
    ("AUTH007", "BK013", "When will the cover design for Midnight in Mysore be ready?",
     "It's been a while since I sent my notes on the cover. Could you tell me when the cover design will "
     "be finalised and how long it will take after that for the book to be published?", 50, None, "open"),
    ("AUTH005", "BK009", "Letters from Lakshadweep 'Currently Unavailable' on Amazon US",
     "A friend in the US tried to buy my book and Amazon US says Currently Unavailable. It shows fine on "
     "Amazon India. Can you check?", 5, None, "open"),
    ("AUTH009", None, "Can I update my author bio?",
     "I'd like to update the author bio that appears on my book pages with my new website link. "
     "Is that possible and how long does it take?", 70,
     "Hi Kavita,\n\nAbsolutely — you can update your author bio at any time. Just reply here with the new "
     "bio and website link, or submit it from your dashboard, and we'll push it to all platforms. Changes "
     "usually reflect within 3–5 business days.\n\nWarm regards,\nBookLeaf Author Support", "resolved"),
]


class Command(BaseCommand):
    help = "Seed authors, books and staff from the BookLeaf sample dataset."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(DEFAULT_DATA))
        parser.add_argument("--demo-tickets", action="store_true", help="Also create sample tickets.")

    @transaction.atomic
    def handle(self, *args, **opts):
        path = Path(opts["file"])
        if not path.exists():
            raise CommandError(f"Data file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))

        author_pw = os.getenv("SEED_AUTHOR_PASSWORD", "author123")
        admin_pw = os.getenv("SEED_ADMIN_PASSWORD", "admin123")

        for email, name in STAFF:
            user, _ = User.objects.update_or_create(
                email=email, defaults={"full_name": name, "role": User.Role.ADMIN, "is_staff": True}
            )
            user.set_password(admin_pw)
            user.save()

        n_books = 0
        for a in data["authors"]:
            user, _ = User.objects.update_or_create(
                email=a["email"].lower(),
                defaults={"full_name": a["name"], "role": User.Role.AUTHOR},
            )
            user.set_password(author_pw)
            user.save()
            author = Author.objects.filter(author_id=a["author_id"]).first()
            if not author:
                author = Author.objects.filter(user=user).first()
            if author:
                author.author_id = a["author_id"]
                author.user = user
                author.phone = a.get("phone", "")
                author.city = a.get("city", "")
                author.joined_date = a.get("joined_date")
                author.save()
            else:
                author = Author.objects.create(
                    author_id=a["author_id"],
                    user=user,
                    phone=a.get("phone", ""),
                    city=a.get("city", ""),
                    joined_date=a.get("joined_date"),
                )
            for b in a["books"]:
                Book.objects.update_or_create(
                    book_id=b["book_id"],
                    defaults={
                        "author": author,
                        "title": b["title"],
                        "isbn": b.get("isbn") or "",
                        "genre": b.get("genre") or "",
                        "publication_date": b.get("publication_date"),
                        "status": b["status"],
                        "mrp": b.get("mrp"),
                        "author_royalty_per_copy": b.get("author_royalty_per_copy"),
                        "total_copies_sold": b.get("total_copies_sold") or 0,
                        "total_royalty_earned": b.get("total_royalty_earned") or 0,
                        "royalty_paid": b.get("royalty_paid") or 0,
                        "royalty_pending": b.get("royalty_pending") or 0,
                        "last_royalty_payout_date": b.get("last_royalty_payout_date"),
                        "print_partner": b.get("print_partner") or "",
                        "available_on": b.get("available_on") or [],
                    },
                )
                n_books += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(data['authors'])} authors, {n_books} books, {len(STAFF)} staff."))

        if opts["demo_tickets"]:
            self._seed_tickets()

    def _seed_tickets(self):
        from apps.support import services
        from apps.support.models import Ticket

        if Ticket.objects.exists():
            self.stdout.write("Tickets already exist; skipping demo tickets.")
            return

        # Classify inline (not in a background thread) so the command doesn't exit mid-call.
        settings.AI["ASYNC_CLASSIFICATION"] = False
        staff = User.objects.get(email=STAFF[1][0])
        now = timezone.now()
        for author_id, book_id, subject, desc, hours_ago, reply, status in DEMO_TICKETS:
            author = Author.objects.get(author_id=author_id)
            book = Book.objects.get(book_id=book_id) if book_id else None
            ticket = services.create_ticket(author=author, book=book, subject=subject, description=desc)
            created = now - timedelta(hours=hours_ago)
            Ticket.objects.filter(pk=ticket.pk).update(created_at=created)
            ticket.refresh_from_db()
            ticket.set_priority(ticket.priority, ticket.priority_source)  # re-anchor SLA to backdated time
            ticket.save(update_fields=["sla_due_at"])
            if reply:
                services.post_message(ticket=ticket, sender=staff, body=reply, new_status=status)
        self.stdout.write(self.style.SUCCESS(f"Created {len(DEMO_TICKETS)} demo tickets."))
