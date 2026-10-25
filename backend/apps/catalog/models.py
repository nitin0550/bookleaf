from datetime import date

from django.conf import settings
from django.db import models


# Ordered production pipeline from the BookLeaf knowledge base.
PRODUCTION_STAGES = [
    "Manuscript Received",
    "Editing",
    "Cover Design",
    "Typesetting",
    "Proofreading",
    "ISBN Assignment",
    "Printing",
    "Distribution Setup",
    "Published & Live",
]
PUBLISHED_STATUS = "Published & Live"


class Author(models.Model):
    """Business profile for an author; login lives on the linked User."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="author_profile"
    )
    author_id = models.CharField(max_length=20, unique=True)  # e.g. AUTH001 (from source data)
    phone = models.CharField(max_length=30, blank=True)
    city = models.CharField(max_length=80, blank=True)
    joined_date = models.DateField(null=True, blank=True)
    bank_account_linked = models.BooleanField(
        default=True,
        help_text="Whether payout bank details are on file. Used in royalty answers.",
    )

    class Meta:
        ordering = ["author_id"]

    @property
    def name(self) -> str:
        return self.user.full_name

    @property
    def email(self) -> str:
        return self.user.email

    def __str__(self):
        return f"{self.author_id} · {self.name}"


class Book(models.Model):
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="books")
    book_id = models.CharField(max_length=20, unique=True)  # e.g. BK001
    title = models.CharField(max_length=255)
    isbn = models.CharField(max_length=32, blank=True)
    genre = models.CharField(max_length=120, blank=True)
    publication_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=80, db_index=True)
    mrp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    author_royalty_per_copy = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_copies_sold = models.PositiveIntegerField(default=0)
    total_royalty_earned = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    royalty_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    royalty_pending = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    last_royalty_payout_date = models.DateField(null=True, blank=True)
    print_partner = models.CharField(max_length=80, blank=True)
    available_on = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["author__author_id", "book_id"]

    def __str__(self):
        return f"{self.book_id} · {self.title}"

    @property
    def is_published(self) -> bool:
        return self.status == PUBLISHED_STATUS

    @property
    def production_stage(self) -> str:
        """'In Production - Cover Design' -> 'Cover Design'; published -> 'Published & Live'."""
        if self.is_published:
            return PUBLISHED_STATUS
        return self.status.split(" - ", 1)[-1].strip()

    @property
    def production_progress(self) -> dict:
        stage = self.production_stage
        index = PRODUCTION_STAGES.index(stage) if stage in PRODUCTION_STAGES else None
        return {
            "stage": stage,
            "step": (index + 1) if index is not None else None,
            "total_steps": len(PRODUCTION_STAGES),
            "stages": PRODUCTION_STAGES,
        }

    def days_since_publication(self, today: date | None = None) -> int | None:
        if not self.publication_date:
            return None
        return ((today or date.today()) - self.publication_date).days
