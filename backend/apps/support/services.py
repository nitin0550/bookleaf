"""
Ticket domain operations. Views stay thin: they validate input and call these.

Each operation records an audit event and bumps ``Ticket.updated_at`` so that
pollers (author and admin UIs) pick up the change on their next tick.
"""
from django.db import transaction
from django.utils import timezone

from apps.ai.services import apply_rules_classification, classify_ticket_async
from config.exceptions import ConflictError

from .models import Category, InternalNote, Priority, Source, Ticket, TicketEvent, TicketMessage


@transaction.atomic
def create_ticket(*, author, book, subject, description, attachment=None) -> Ticket:
    ticket = Ticket(author=author, book=book, subject=subject.strip(),
                    description=description.strip(), attachment=attachment)
    # Rules give an immediate category/priority; the AI refines it moments later.
    apply_rules_classification(ticket)
    ticket.save()
    ticket.set_priority(ticket.priority, ticket.priority_source)  # anchor SLA to created_at
    ticket.save(update_fields=["sla_due_at"])
    TicketEvent.objects.create(ticket=ticket, actor=author.user, kind=TicketEvent.Kind.CREATED)
    classify_ticket_async(ticket.pk)
    return ticket


@transaction.atomic
def post_message(*, ticket: Ticket, sender, body: str, ai_assisted: bool = False,
                 new_status: str | None = None) -> TicketMessage:
    ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if ticket.status == Ticket.Status.CLOSED:
        raise ConflictError("This ticket is closed. Please open a new ticket.")

    is_staff = sender.is_admin
    message = TicketMessage.objects.create(
        ticket=ticket, sender=sender, sender_role="admin" if is_staff else "author",
        body=body.strip(), ai_assisted=ai_assisted and is_staff,
    )
    TicketEvent.objects.create(ticket=ticket, actor=sender, kind=TicketEvent.Kind.REPLIED,
                               to_value="staff" if is_staff else "author")

    now = timezone.now()
    if is_staff:
        ticket.awaiting_staff = False
        ticket.first_response_at = ticket.first_response_at or now
        if ticket.assigned_to_id is None:
            ticket.assigned_to = sender
            TicketEvent.objects.create(ticket=ticket, actor=sender, kind=TicketEvent.Kind.ASSIGNED,
                                       to_value=sender.full_name)
        target = new_status or (Ticket.Status.IN_PROGRESS if ticket.status == Ticket.Status.OPEN else None)
        if target:
            _change_status(ticket, target, sender)
    else:
        ticket.awaiting_staff = True
        # An author follow-up re-opens a resolved ticket.
        if ticket.status == Ticket.Status.RESOLVED:
            _change_status(ticket, Ticket.Status.OPEN, sender)
    ticket.save()
    return message


def _change_status(ticket: Ticket, new_status: str, actor) -> None:
    if ticket.status == new_status:
        return
    TicketEvent.objects.create(ticket=ticket, actor=actor, kind=TicketEvent.Kind.STATUS,
                               from_value=ticket.status, to_value=new_status)
    ticket.status = new_status
    if new_status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
        ticket.resolved_at = ticket.resolved_at or timezone.now()
    else:
        ticket.resolved_at = None


@transaction.atomic
def update_ticket(*, ticket: Ticket, actor, status=None, category=None, priority=None,
                  assigned_to=..., ) -> Ticket:
    """Staff updates. ``assigned_to=...`` (Ellipsis) means 'not provided'; None means unassign."""
    ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)

    if status and status != ticket.status:
        _change_status(ticket, status, actor)

    if category and (category != ticket.category or ticket.category_source != Source.ADMIN):
        TicketEvent.objects.create(ticket=ticket, actor=actor, kind=TicketEvent.Kind.CATEGORY,
                                   from_value=Category(ticket.category).label,
                                   to_value=Category(category).label)
        ticket.set_category(category, Source.ADMIN)

    if priority and (priority != ticket.priority or ticket.priority_source != Source.ADMIN):
        TicketEvent.objects.create(ticket=ticket, actor=actor, kind=TicketEvent.Kind.PRIORITY,
                                   from_value=Priority(ticket.priority).label,
                                   to_value=Priority(priority).label)
        ticket.set_priority(priority, Source.ADMIN)

    if assigned_to is not ... and assigned_to != ticket.assigned_to:
        TicketEvent.objects.create(ticket=ticket, actor=actor, kind=TicketEvent.Kind.ASSIGNED,
                                   from_value=ticket.assigned_to.full_name if ticket.assigned_to else "",
                                   to_value=assigned_to.full_name if assigned_to else "Unassigned")
        ticket.assigned_to = assigned_to

    ticket.save()
    return ticket


def add_internal_note(*, ticket: Ticket, author, body: str) -> InternalNote:
    note = InternalNote.objects.create(ticket=ticket, created_by=author, body=body.strip())
    Ticket.objects.filter(pk=ticket.pk).update(updated_at=timezone.now())
    return note
