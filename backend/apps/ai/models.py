from django.db import models


class AIUsageLog(models.Model):
    """One row per LLM call (successful or not). Powers the cost/health panel."""

    class Operation(models.TextChoices):
        CLASSIFY = "classify"
        DRAFT = "draft"

    operation = models.CharField(max_length=20, choices=Operation.choices, db_index=True)
    model = models.CharField(max_length=80)
    ticket = models.ForeignKey(
        "support.Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_calls"
    )
    success = models.BooleanField(default=True)
    error_type = models.CharField(max_length=80, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class AIDraft(models.Model):
    """Cached draft reply for a ticket.

    A draft is reused as long as its ``context_key`` (a hash of everything the
    prompt depends on) still matches, so repeatedly opening a ticket costs zero
    extra tokens. A new author message or a category change invalidates it.
    """

    class Source(models.TextChoices):
        AI = "ai", "AI model"
        TEMPLATE = "template", "Policy template (AI unavailable)"

    ticket = models.ForeignKey("support.Ticket", on_delete=models.CASCADE, related_name="ai_drafts")
    context_key = models.CharField(max_length=64, db_index=True)
    body = models.TextField()
    suggested_status = models.CharField(max_length=20, blank=True)
    agent_notes = models.TextField(blank=True)
    source = models.CharField(max_length=10, choices=Source.choices)
    model = models.CharField(max_length=80, blank=True)
    kb_sections = models.JSONField(default=list)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
