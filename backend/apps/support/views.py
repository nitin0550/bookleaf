import os
from datetime import timedelta

from django.conf import settings
from django.db.models import Avg, BooleanField, Count, ExpressionWrapper, F, Prefetch, Q, Sum
from django_filters.rest_framework import DjangoFilterBackend
from django.http import FileResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from rest_framework.permissions import AllowAny
from apps.accounts.permissions import IsAdmin, IsAuthor
from apps.ai.llm import ai_enabled, breaker_is_open
from apps.ai.models import AIUsageLog
from apps.ai.services import classify_ticket, get_or_create_draft

from . import services
from .filters import TicketFilter
from .models import AIStatus, Category, Priority, Source, Ticket, TicketMessage
from .serializers import (
    AdminTicketDetailSerializer, AdminTicketListSerializer, AdminTicketUpdateSerializer,
    AIDraftSerializer, AuthorTicketDetailSerializer, AuthorTicketListSerializer,
    InternalNoteSerializer, MessageCreateSerializer, MessageSerializer, StaffMessageSerializer,
    TicketCreateSerializer,
)

ORDERINGS = {
    # Default queue order: unresolved first, then most urgent, then oldest.
    "urgency": ["-is_open", "priority_rank", "created_at"],
    "oldest": ["created_at"],
    "newest": ["-created_at"],
    "updated": ["-updated_at"],
}


@extend_schema_view(
    list=extend_schema(
        summary="List tickets",
        description="Authors see only their own tickets. Staff see all tickets and can filter.",
        parameters=[OpenApiParameter("ordering", str, enum=list(ORDERINGS), description="Default: urgency")],
    ),
    retrieve=extend_schema(summary="Get a ticket (thread, and for staff: notes, events, author context)"),
    create=extend_schema(summary="Raise a support ticket (authors only)", request=TicketCreateSerializer,
                         responses={201: AuthorTicketDetailSerializer}),
    partial_update=extend_schema(summary="Update status / category / priority / assignee (staff only)",
                                 request=AdminTicketUpdateSerializer,
                                 responses={200: AdminTicketDetailSerializer}),
)
class TicketViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                    viewsets.GenericViewSet):
    filterset_class = TicketFilter
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "head", "options"]
    # Ordering is a named, explicit choice (see ORDERINGS) rather than arbitrary fields.
    filter_backends = [DjangoFilterBackend]

    # ---- scoping -----------------------------------------------------------
    def get_queryset(self):
        """Every action starts here, so an author can never load another author's ticket:
        out-of-scope ids simply 404."""
        if getattr(self, "swagger_fake_view", False):  # OpenAPI schema generation
            return Ticket.objects.none()
        user = self.request.user
        qs = Ticket.objects.select_related("author__user", "book", "assigned_to")
        if not user.is_admin:
            qs = qs.filter(author__user=user)
        if self.action == "list":
            qs = qs.prefetch_related(Prefetch("messages", queryset=TicketMessage.objects.only(
                "id", "ticket_id", "sender_role", "created_at")))
        elif self.action == "retrieve":
            qs = self._with_detail_prefetches(qs)
        qs = qs.annotate(is_open=ExpressionWrapper(Q(status__in=Ticket.UNRESOLVED_STATUSES),
                                                   output_field=BooleanField()))
        ordering = self.request.query_params.get("ordering", "urgency")
        return qs.order_by(*ORDERINGS.get(ordering, ORDERINGS["urgency"]))

    def get_serializer_class(self):
        staff = self.request.user.is_authenticated and self.request.user.is_admin
        if self.action == "create":
            return TicketCreateSerializer
        if self.action == "partial_update":
            return AdminTicketUpdateSerializer
        if self.action == "list":
            return AdminTicketListSerializer if staff else AuthorTicketListSerializer
        return AdminTicketDetailSerializer if staff else AuthorTicketDetailSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthor()]
        if self.action in {"partial_update", "notes", "assign_to_me", "ai_draft", "reclassify"}:
            return [IsAdmin()]
        return super().get_permissions()

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "ticket_create"
            return [ScopedRateThrottle()]
        if self.action == "ai_draft" and self.request.method == "POST":
            self.throttle_scope = "ai_draft"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def _with_detail_prefetches(self, qs):
        qs = qs.prefetch_related("messages__sender")
        if self.request.user.is_admin:
            qs = qs.prefetch_related("internal_notes__created_by", "events__actor", "author__books")
        return qs

    def _detail_response(self, ticket, status_code=status.HTTP_200_OK):
        """Re-read the ticket after a write and return the caller's detail representation."""
        fresh = self._with_detail_prefetches(
            Ticket.objects.select_related("author__user", "book", "assigned_to")
        ).get(pk=ticket.pk)
        serializer_cls = (AdminTicketDetailSerializer if self.request.user.is_admin
                          else AuthorTicketDetailSerializer)
        return Response(serializer_cls(fresh, context=self.get_serializer_context()).data,
                        status=status_code)

    # ---- CRUD --------------------------------------------------------------
    def create(self, request, *args, **kwargs):
        serializer = TicketCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ticket = services.create_ticket(
            author=request.user.author_profile, book=data.get("book_id"),
            subject=data["subject"], description=data["description"],
            attachment=data.get("attachment"),
        )
        return self._detail_response(ticket, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = AdminTicketUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.update_ticket(
            ticket=ticket, actor=request.user, status=data.get("status"),
            category=data.get("category"), priority=data.get("priority"),
            assigned_to=data["assigned_to"] if "assigned_to" in data else ...,
        )
        return self._detail_response(ticket)

    # ---- sub-resources -----------------------------------------------------
    @extend_schema(summary="Post a public reply (author follow-up or staff response)",
                   request=MessageCreateSerializer, responses={201: MessageSerializer})
    @action(detail=True, methods=["post"])
    def messages(self, request, pk=None):
        ticket = self.get_object()  # scoping guarantees authors can only reply to their own tickets
        serializer = MessageCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        message = services.post_message(
            ticket=ticket, sender=request.user, body=serializer.validated_data["body"],
            ai_assisted=serializer.validated_data.get("ai_assisted", False),
            new_status=serializer.validated_data.get("status"),
        )
        out = StaffMessageSerializer if request.user.is_admin else MessageSerializer
        return Response(out(message).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="List or add internal notes (staff only, never visible to authors)",
                   request=InternalNoteSerializer, responses={200: InternalNoteSerializer(many=True),
                                                              201: InternalNoteSerializer})
    @action(detail=True, methods=["get", "post"])
    def notes(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "GET":
            notes = ticket.internal_notes.select_related("created_by")
            return Response(InternalNoteSerializer(notes, many=True).data)
        serializer = InternalNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = services.add_internal_note(ticket=ticket, author=request.user,
                                          body=serializer.validated_data["body"])
        return Response(InternalNoteSerializer(note).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Assign the ticket to the current staff member", request=None,
                   responses={200: AdminTicketDetailSerializer})
    @action(detail=True, methods=["post"], url_path="assign-to-me")
    def assign_to_me(self, request, pk=None):
        ticket = self.get_object()
        services.update_ticket(ticket=ticket, actor=request.user, assigned_to=request.user)
        return self._detail_response(ticket)

    @extend_schema(
        summary="Get the AI-drafted reply (GET = cached if still valid; POST = force regenerate)",
        request=None, responses={200: AIDraftSerializer},
    )
    @action(detail=True, methods=["get", "post"], url_path="ai-draft")
    def ai_draft(self, request, pk=None):
        ticket = self.get_object()
        draft, cached = get_or_create_draft(ticket, force=request.method == "POST")
        return Response(AIDraftSerializer(draft, context={"cached": cached}).data)

    @extend_schema(summary="Download the ticket's attachment (same access rules as the ticket)",
                   responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def attachment(self, request, pk=None):
        # Attachments are private: served through the API (scoped + authenticated),
        # never from a public /media URL.
        ticket = self.get_object()
        if not ticket.attachment:
            raise NotFound("This ticket has no attachment.")
        return FileResponse(ticket.attachment.open("rb"), as_attachment=False,
                            filename=os.path.basename(ticket.attachment.name))

    @extend_schema(summary="Re-run AI classification (e.g. after an outage)", request=None,
                   responses={200: AdminTicketDetailSerializer})
    @action(detail=True, methods=["post"])
    def reclassify(self, request, pk=None):
        ticket = self.get_object()
        classify_ticket(ticket.pk)  # synchronous: staff explicitly asked and is waiting
        return self._detail_response(ticket)

    @extend_schema(
        summary="Lightweight change feed for near-real-time updates",
        description=(
            "Returns ids of tickets (visible to the caller) updated after `since`, plus the "
            "server time to use as the next `since`. Clients poll this cheaply every few seconds "
            "and only refetch full data when something changed."
        ),
        parameters=[OpenApiParameter("since", OpenApiTypes.DATETIME, required=False)],
    )
    @action(detail=False, methods=["get"])
    def changes(self, request):
        now = timezone.now()
        since_raw = request.query_params.get("since")
        qs = Ticket.objects.all() if request.user.is_admin else Ticket.objects.filter(
            author__user=request.user)
        if since_raw:
            since = parse_datetime(since_raw.replace(" ", "+"))
            if since is None:
                raise ValidationError({"since": ["Use an ISO-8601 datetime."]})
            if timezone.is_naive(since):
                since = timezone.make_aware(since)
            # Small overlap guards against clock/commit races; clients dedupe by id.
            qs = qs.filter(updated_at__gt=since - timedelta(seconds=2))
        else:
            qs = qs.none()
        changed = list(qs.values("id", "updated_at")[:200])
        return Response({"server_time": now.isoformat(), "changed": changed})


class AdminStatsView(APIView):
    """Queue health + AI performance/cost for the staff dashboard."""

    permission_classes = [IsAdmin]

    @extend_schema(summary="Queue and AI statistics (staff only)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        tickets = Ticket.objects.all()
        unresolved = tickets.filter(status__in=Ticket.UNRESOLVED_STATUSES)
        now = timezone.now()

        by_status = dict(tickets.values_list("status").annotate(n=Count("id")))
        by_priority = dict(unresolved.values_list("priority").annotate(n=Count("id")))
        overdue = unresolved.filter(first_response_at__isnull=True, sla_due_at__lt=now).count()

        ai_done = tickets.filter(ai_status=AIStatus.COMPLETED)
        reviewed = ai_done.filter(Q(category_source=Source.ADMIN) | Q(priority_source=Source.ADMIN))
        cat_overrides = ai_done.filter(category_source=Source.ADMIN).exclude(category=F("ai_category")).count()
        pri_overrides = ai_done.filter(priority_source=Source.ADMIN).exclude(priority=F("ai_priority")).count()
        n_ai = ai_done.count()

        since = now - timedelta(days=30)
        usage = AIUsageLog.objects.filter(created_at__gte=since)
        agg = usage.aggregate(inp=Sum("input_tokens"), out=Sum("output_tokens"),
                              calls=Count("id"), failures=Count("id", filter=Q(success=False)),
                              latency=Avg("latency_ms", filter=Q(success=True)))
        price_in, price_out = settings.AI["PRICE_INPUT_PER_MTOK"], settings.AI["PRICE_OUTPUT_PER_MTOK"]
        est_cost = ((agg["inp"] or 0) * price_in + (agg["out"] or 0) * price_out) / 1_000_000
        per_op = {
            row["operation"]: {
                "calls": row["calls"],
                "avg_input_tokens": round(row["avg_in"] or 0),
                "avg_output_tokens": round(row["avg_out"] or 0),
            }
            for row in usage.filter(success=True).values("operation").annotate(
                calls=Count("id"), avg_in=Avg("input_tokens"), avg_out=Avg("output_tokens"))
        }
        ai_messages = TicketMessage.objects.filter(sender_role="admin")

        return Response({
            "queue": {
                "by_status": {s.value: by_status.get(s.value, 0) for s in Ticket.Status},
                "unresolved_by_priority": {p.value: by_priority.get(p.value, 0) for p in Priority},
                "overdue": overdue,
                "awaiting_staff": unresolved.filter(awaiting_staff=True).count(),
                "unassigned": unresolved.filter(assigned_to__isnull=True).count(),
            },
            "ai": {
                "enabled": ai_enabled(),
                "model": settings.AI["MODEL"] if ai_enabled() else None,
                "circuit_open": breaker_is_open(),
                "classified_by_ai": n_ai,
                "classification_failures": tickets.filter(ai_status=AIStatus.FAILED).count(),
                "category_override_rate": round(cat_overrides / n_ai, 3) if n_ai else None,
                "priority_override_rate": round(pri_overrides / n_ai, 3) if n_ai else None,
                "tickets_reviewed_by_staff": reviewed.count(),
                "replies_ai_assisted": ai_messages.filter(ai_assisted=True).count(),
                "replies_total": ai_messages.count(),
                "last_30_days": {
                    "calls": agg["calls"] or 0,
                    "failures": agg["failures"] or 0,
                    "input_tokens": agg["inp"] or 0,
                    "output_tokens": agg["out"] or 0,
                    "avg_latency_ms": round(agg["latency"] or 0),
                    "estimated_cost_usd": round(est_cost, 4),
                    "by_operation": per_op,
                },
            },
        })


class MetaView(APIView):
    """Enumerations for building forms and filters on the client."""

    permission_classes = [AllowAny]

    @extend_schema(summary="Ticket enumerations (statuses, categories, priorities)",
                   responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response({
            "statuses": [{"value": s.value, "label": s.label} for s in Ticket.Status],
            "categories": [{"value": c.value, "label": c.label} for c in Category],
            "priorities": [{"value": p.value, "label": p.label} for p in Priority],
        })
