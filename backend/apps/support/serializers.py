"""
Serializers are split by audience on purpose.

Author-facing serializers do not reference internal notes, AI internals,
priority, or assignment at all — so there is no field that a future change
could accidentally expose. Staff serializers extend them.
"""
import os

from django.conf import settings
from rest_framework import serializers

from apps.accounts.models import User
from apps.ai.models import AIDraft
from apps.catalog.models import Book
from apps.catalog.serializers import AuthorContextSerializer, AuthorRefSerializer, BookRefSerializer

from .models import Category, InternalNote, Priority, Ticket, TicketEvent, TicketMessage


# ----------------------------------------------------------------------------- shared

class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = TicketMessage
        fields = ["id", "sender_role", "sender_name", "body", "created_at"]

    def get_sender_name(self, obj) -> str:
        if obj.sender_role == "admin":
            first = (obj.sender.full_name or "").split(" ")[0]
            return f"{first} · BookLeaf Support" if first else "BookLeaf Support"
        return obj.sender.full_name


class StaffMessageSerializer(MessageSerializer):
    class Meta(MessageSerializer.Meta):
        fields = MessageSerializer.Meta.fields + ["ai_assisted"]


def _attachment_url(serializer, obj):
    if not obj.attachment:
        return None
    request = serializer.context.get("request")
    url = obj.attachment.url
    return request.build_absolute_uri(url) if request else url


# ----------------------------------------------------------------------------- author

class AuthorTicketListSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(read_only=True)
    book = BookRefSerializer(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    last_reply_from = serializers.SerializerMethodField()
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = ["id", "reference", "subject", "status", "status_label", "category_label",
                  "book", "created_at", "updated_at", "last_reply_from", "message_count"]

    def get_last_reply_from(self, obj) -> str | None:
        last = obj.messages.all()
        last = last[len(last) - 1] if last else None  # uses prefetch cache
        return last.sender_role if last else None

    def get_message_count(self, obj) -> int:
        return len(obj.messages.all())


class AuthorTicketDetailSerializer(AuthorTicketListSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    attachment_url = serializers.SerializerMethodField()

    class Meta(AuthorTicketListSerializer.Meta):
        fields = AuthorTicketListSerializer.Meta.fields + ["description", "attachment_url", "messages"]

    def get_attachment_url(self, obj) -> str | None:
        return _attachment_url(self, obj)


class TicketCreateSerializer(serializers.Serializer):
    book_id = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        help_text="Book the query is about (e.g. BK001). Omit or null for General / Account level.",
    )
    subject = serializers.CharField(min_length=5, max_length=200)
    description = serializers.CharField(min_length=20, max_length=5000)
    attachment = serializers.FileField(required=False, allow_null=True)

    def validate_book_id(self, value):
        if not value:
            return None
        author = self.context["request"].user.author_profile
        try:
            return Book.objects.get(book_id=value, author=author)
        except Book.DoesNotExist:
            raise serializers.ValidationError("You don't have a book with this ID.")

    def validate_attachment(self, f):
        if not f:
            return None
        if f.size > settings.ATTACHMENT_MAX_BYTES:
            mb = settings.ATTACHMENT_MAX_BYTES // (1024 * 1024)
            raise serializers.ValidationError(f"Attachments must be {mb} MB or smaller.")
        ext = os.path.splitext(f.name)[1].lower().lstrip(".")
        if ext not in settings.ATTACHMENT_ALLOWED_EXTENSIONS:
            allowed = ", ".join(settings.ATTACHMENT_ALLOWED_EXTENSIONS)
            raise serializers.ValidationError(f"Unsupported file type. Allowed: {allowed}.")
        return f

    def validate_subject(self, value):
        return " ".join(value.split())


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(min_length=2, max_length=5000)
    ai_assisted = serializers.BooleanField(default=False, help_text="Staff only: reply started from the AI draft.")
    status = serializers.ChoiceField(
        choices=[Ticket.Status.IN_PROGRESS, Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
        required=False, help_text="Staff only: set the ticket status together with the reply.",
    )

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.is_admin and ("status" in attrs or attrs.get("ai_assisted")):
            raise serializers.ValidationError("Authors cannot set status or ai_assisted.")
        return attrs


# ----------------------------------------------------------------------------- staff

class StaffUserRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name"]


class AdminTicketListSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(read_only=True)
    author = AuthorRefSerializer(read_only=True)
    book = BookRefSerializer(read_only=True)
    assigned_to = StaffUserRefSerializer(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id", "reference", "subject", "author", "book", "status", "status_label",
            "category", "category_label", "category_source", "priority", "priority_label",
            "priority_source", "ai_status", "ai_confidence", "ai_summary", "assigned_to",
            "awaiting_staff", "is_overdue", "sla_due_at", "first_response_at",
            "created_at", "updated_at",
        ]


class InternalNoteSerializer(serializers.ModelSerializer):
    created_by = StaffUserRefSerializer(read_only=True)

    class Meta:
        model = InternalNote
        fields = ["id", "body", "created_by", "created_at"]
        read_only_fields = ["id", "created_by", "created_at"]
        extra_kwargs = {"body": {"min_length": 2, "max_length": 5000}}


class TicketEventSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = TicketEvent
        fields = ["id", "kind", "from_value", "to_value", "actor", "created_at"]

    def get_actor(self, obj) -> str:
        return obj.actor.full_name if obj.actor else "System"


class AdminTicketDetailSerializer(AdminTicketListSerializer):
    messages = StaffMessageSerializer(many=True, read_only=True)
    internal_notes = InternalNoteSerializer(many=True, read_only=True)
    events = TicketEventSerializer(many=True, read_only=True)
    author_context = AuthorContextSerializer(source="author", read_only=True)
    attachment_url = serializers.SerializerMethodField()

    class Meta(AdminTicketListSerializer.Meta):
        fields = AdminTicketListSerializer.Meta.fields + [
            "description", "attachment_url", "ai_category", "ai_priority", "ai_rationale",
            "resolved_at", "messages", "internal_notes", "events", "author_context",
        ]

    def get_attachment_url(self, obj) -> str | None:
        return _attachment_url(self, obj)


class AdminTicketUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Ticket.Status.choices, required=False)
    category = serializers.ChoiceField(choices=Category.choices, required=False)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.ADMIN, is_active=True),
        required=False, allow_null=True,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one of: status, category, priority, assigned_to.")
        return attrs


class AIDraftSerializer(serializers.ModelSerializer):
    cached = serializers.SerializerMethodField()

    class Meta:
        model = AIDraft
        fields = ["body", "source", "suggested_status", "agent_notes", "model", "kb_sections",
                  "input_tokens", "output_tokens", "created_at", "cached"]

    def get_cached(self, obj) -> bool:
        return bool(self.context.get("cached"))
