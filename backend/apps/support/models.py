from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Category(models.TextChoices):
    ROYALTY = "royalty_payments", "Royalty & Payments"
    ISBN = "isbn_metadata", "ISBN & Metadata Issues"
    PRINTING = "printing_quality", "Printing & Quality"
    DISTRIBUTION = "distribution_availability", "Distribution & Availability"
    PRODUCTION = "book_status_production", "Book Status & Production Updates"
    GENERAL = "general_inquiry", "General Inquiry"


class Priority(models.TextChoices):
    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


PRIORITY_RANK = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}

# First-response targets used to surface tickets that are at risk.
SLA_HOURS = {Priority.CRITICAL: 4, Priority.HIGH: 24, Priority.MEDIUM: 48, Priority.LOW: 72}


class Source(models.TextChoices):
    """Where a classification/priority value came from."""

    AI = "ai", "AI model"
    RULES = "rules", "Keyword rules (AI unavailable)"
    ADMIN = "admin", "Set by staff"


class AIStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed (rules fallback used)"
    DISABLED = "disabled", "AI disabled (rules fallback used)"


class Ticket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    UNRESOLVED_STATUSES = (Status.OPEN, Status.IN_PROGRESS)

    author = models.ForeignKey("catalog.Author", on_delete=models.CASCADE, related_name="tickets")
    book = models.ForeignKey(
        "catalog.Book", on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets",
        help_text="Null means the query is General / Account level.",
    )
    subject = models.CharField(max_length=200)
    description = models.TextField()
    attachment = models.FileField(upload_to="attachments/%Y/%m/", null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)

    # Effective values (what the queue shows and filters on).
    category = models.CharField(max_length=40, choices=Category.choices, db_index=True)
    category_source = models.CharField(max_length=10, choices=Source.choices, default=Source.RULES)
    priority = models.CharField(max_length=10, choices=Priority.choices, db_index=True)
    priority_source = models.CharField(max_length=10, choices=Source.choices, default=Source.RULES)
    priority_rank = models.PositiveSmallIntegerField(default=2, db_index=True)

    # What the AI originally said — kept even after an admin override so we can
    # measure classification accuracy (override rate) over time.
    ai_status = models.CharField(max_length=12, choices=AIStatus.choices, default=AIStatus.PENDING)
    ai_category = models.CharField(max_length=40, choices=Category.choices, blank=True)
    ai_priority = models.CharField(max_length=10, choices=Priority.choices, blank=True)
    ai_confidence = models.FloatField(null=True, blank=True)
    ai_rationale = models.TextField(blank=True)
    ai_summary = models.CharField(max_length=300, blank=True)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_tickets", limit_choices_to={"role": "admin"},
    )
    awaiting_staff = models.BooleanField(
        default=True, help_text="True when the last public message came from the author."
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    sla_due_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["priority_rank", "created_at"]
        indexes = [
            models.Index(fields=["status", "priority_rank", "created_at"]),
            models.Index(fields=["author", "-updated_at"]),
        ]

    def __str__(self):
        return f"{self.reference} · {self.subject}"

    @property
    def reference(self) -> str:
        return f"BL-{self.pk:05d}" if self.pk else "BL-new"

    @property
    def is_unresolved(self) -> bool:
        return self.status in self.UNRESOLVED_STATUSES

    @property
    def is_overdue(self) -> bool:
        return bool(
            self.is_unresolved
            and self.first_response_at is None
            and self.sla_due_at
            and timezone.now() > self.sla_due_at
        )

    def set_priority(self, priority: str, source: str):
        self.priority = priority
        self.priority_source = source
        self.priority_rank = PRIORITY_RANK[Priority(priority)]
        base = self.created_at or timezone.now()
        self.sla_due_at = base + timedelta(hours=SLA_HOURS[Priority(priority)])

    def set_category(self, category: str, source: str):
        self.category = category
        self.category_source = source


class TicketMessage(models.Model):
    """A public message on a ticket, visible to both the author and staff."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    sender_role = models.CharField(max_length=10)  # snapshot: "author" | "admin"
    body = models.TextField()
    ai_assisted = models.BooleanField(default=False, help_text="Started from an AI draft.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class InternalNote(models.Model):
    """Staff-only note. Stored separately from messages so it can never leak to authors
    through a missed filter: author-facing serializers simply don't know this model."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="internal_notes")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class TicketEvent(models.Model):
    """Audit trail: status changes, overrides, assignments, AI results."""

    class Kind(models.TextChoices):
        CREATED = "created"
        STATUS = "status_changed"
        CATEGORY = "category_changed"
        PRIORITY = "priority_changed"
        ASSIGNED = "assigned"
        AI_CLASSIFIED = "ai_classified"
        AI_FAILED = "ai_failed"
        REPLIED = "replied"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Null for system/AI actions.",
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    from_value = models.CharField(max_length=120, blank=True)
    to_value = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
