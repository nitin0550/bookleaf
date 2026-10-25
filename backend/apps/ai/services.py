"""
AI use-cases: ticket triage and reply drafting.

Both functions are safe to call at any time: they never raise because of the
AI provider. On any ``AIUnavailable`` they fall back (rules / templates) and
record what happened so the UI can tell staff which values came from where.
"""
from __future__ import annotations

import hashlib
import logging
import threading

from django.db import close_old_connections, transaction

from apps.support.models import AIStatus, Category, Priority, Source, Ticket, TicketEvent

from . import knowledge_base as kb
from .context import author_facts, classification_hints, thread_text
from .llm import AIUnavailable, ai_enabled, get_client
from .models import AIDraft
from .prompts import (
    CLASSIFY_SYSTEM, CLASSIFY_TOOL, DRAFT_SYSTEM_TEMPLATE, DRAFT_TOOL,
    classify_user_message, draft_user_message,
)
from .rules import classify_by_rules
from .templates import template_draft

logger = logging.getLogger("apps.ai")

# Bump when prompts change so cached drafts built from old prompts are not reused.
PROMPT_VERSION = "v3"
CLASSIFY_MAX_TOKENS = 300
DRAFT_MAX_TOKENS = 900
CLASSIFY_DESCRIPTION_CHARS = 1500  # triage needs the gist, not the whole essay


# --------------------------------------------------------------------------- triage

def apply_rules_classification(ticket: Ticket) -> None:
    """Instant, deterministic first pass so a new ticket is never uncategorised."""
    result = classify_by_rules(ticket.subject, ticket.description)
    ticket.set_category(result.category, Source.RULES)
    ticket.set_priority(result.priority, Source.RULES)


def classify_ticket(ticket_id: int) -> None:
    """Ask the LLM to classify a ticket and store the result.

    Admin overrides always win: if staff already changed a value, we still
    record the AI's opinion (for accuracy tracking) but don't overwrite theirs.
    """
    ticket = Ticket.objects.select_related("book", "author__user").get(pk=ticket_id)

    if not ai_enabled():
        Ticket.objects.filter(pk=ticket.pk).update(ai_status=AIStatus.DISABLED)
        return

    try:
        client = get_client()
        result = client.call_tool(
            operation="classify",
            system=CLASSIFY_SYSTEM,
            user=classify_user_message(
                ticket.subject,
                ticket.description[:CLASSIFY_DESCRIPTION_CHARS],
                classification_hints(ticket),
            ),
            tool=CLASSIFY_TOOL,
            max_tokens=CLASSIFY_MAX_TOKENS,
            ticket=ticket,
        )
        data = _validate_triage(result.data)
    except AIUnavailable as exc:
        logger.info("Classification fell back to rules for ticket %s: %s", ticket.pk, exc.reason)
        with transaction.atomic():
            Ticket.objects.filter(pk=ticket.pk).update(ai_status=AIStatus.FAILED)
            TicketEvent.objects.create(ticket=ticket, kind=TicketEvent.Kind.AI_FAILED, to_value=exc.reason[:120])
        return

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        ticket.ai_category = data["category"]
        ticket.ai_priority = data["priority"]
        ticket.ai_confidence = data["confidence"]
        ticket.ai_rationale = data["rationale"]
        ticket.ai_summary = data["summary"]
        ticket.ai_status = AIStatus.COMPLETED
        if ticket.category_source != Source.ADMIN:
            ticket.set_category(data["category"], Source.AI)
        if ticket.priority_source != Source.ADMIN:
            ticket.set_priority(data["priority"], Source.AI)
        ticket.save()
        TicketEvent.objects.create(
            ticket=ticket, kind=TicketEvent.Kind.AI_CLASSIFIED,
            to_value=f"{Category(data['category']).label} · {Priority(data['priority']).label}",
        )


def _validate_triage(data: dict) -> dict:
    """The tool schema constrains the model, but we never trust it blindly."""
    try:
        category = Category(data["category"]).value
        priority = Priority(data["priority"]).value
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (KeyError, ValueError, TypeError) as exc:
        raise AIUnavailable(f"AI returned invalid triage values ({exc}).") from exc
    return {
        "category": category,
        "priority": priority,
        "confidence": confidence,
        "rationale": str(data.get("rationale", ""))[:500],
        "summary": str(data.get("summary", ""))[:300],
    }


def classify_ticket_async(ticket_id: int) -> None:
    """Fire-and-forget classification after the creating transaction commits.

    A daemon thread keeps the demo deployment to a single process. In
    production this becomes a Celery/RQ task with retries — same function body.
    """
    from django.conf import settings

    def run():
        close_old_connections()
        try:
            classify_ticket(ticket_id)
        except Exception:  # never let a background failure crash anything
            logger.exception("Background classification crashed for ticket %s", ticket_id)
        finally:
            close_old_connections()

    if settings.AI.get("ASYNC_CLASSIFICATION", True):
        transaction.on_commit(lambda: threading.Thread(target=run, daemon=True).start())
    else:
        transaction.on_commit(run)


# --------------------------------------------------------------------------- drafting

def _context_key(ticket: Ticket) -> str:
    """Everything the draft depends on. If none of it changed, reuse the cached draft."""
    last_msg = ticket.messages.order_by("-id").values_list("id", flat=True).first()
    book = ticket.book
    book_sig = (
        f"{book.status}|{book.royalty_pending}|{book.last_royalty_payout_date}" if book else "none"
    )
    raw = "|".join([
        PROMPT_VERSION, ticket.category, str(ticket.book_id), str(last_msg),
        book_sig, str(ticket.author.bank_account_linked),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


def get_or_create_draft(ticket: Ticket, *, force: bool = False) -> tuple[AIDraft, bool]:
    """Return (draft, from_cache). Never raises due to the AI provider."""
    key = _context_key(ticket)
    if not force:
        cached = ticket.ai_drafts.filter(context_key=key, source=AIDraft.Source.AI).first()
        if cached:
            return cached, True

    sections = kb.sections_for(ticket.category)
    section_keys = [s.key for s in sections]

    if ai_enabled():
        try:
            client = get_client()
            system = DRAFT_SYSTEM_TEMPLATE.format(
                kb=kb.render_sections(sections),
                examples=kb.render_examples(ticket.category) or "(none for this category)",
            )
            user = draft_user_message(
                Category(ticket.category).label, author_facts(ticket), thread_text(ticket)
            )
            result = client.call_tool(
                operation="draft", system=system, user=user, tool=DRAFT_TOOL,
                max_tokens=DRAFT_MAX_TOKENS, ticket=ticket,
            )
            reply = str(result.data.get("reply", "")).strip()
            if len(reply) < 40:
                raise AIUnavailable("AI draft was empty or too short.")
            suggested = result.data.get("suggested_status")
            draft = AIDraft.objects.create(
                ticket=ticket, context_key=key, body=reply,
                suggested_status=suggested if suggested in {"in_progress", "resolved"} else "",
                agent_notes=str(result.data.get("agent_notes", ""))[:1000],
                source=AIDraft.Source.AI, model=result.model, kb_sections=section_keys,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            )
            return draft, False
        except AIUnavailable as exc:
            logger.info("Draft fell back to template for ticket %s: %s", ticket.pk, exc.reason)

    # Templates are free to rebuild, so they are not persisted (unsaved instance).
    reply, suggested = template_draft(ticket)
    draft = AIDraft(
        ticket=ticket, context_key=key, body=reply, suggested_status=suggested,
        agent_notes="AI is unavailable — this is a policy template. Fill any [bracketed] placeholders before sending.",
        source=AIDraft.Source.TEMPLATE, kb_sections=section_keys,
    )
    return draft, False
