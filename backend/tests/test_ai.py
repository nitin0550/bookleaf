"""AI integration: structured triage, override safety, caching, and graceful degradation."""
from datetime import date

import pytest

from apps.ai import knowledge_base as kb
from apps.ai.models import AIDraft
from apps.ai.rules import classify_by_rules
from apps.ai.services import classify_ticket, get_or_create_draft
from apps.catalog.models import Book
from apps.catalog.royalty import book_royalty_flags, payout_schedule
from apps.support.models import Category, Ticket

pytestmark = pytest.mark.django_db

ROYALTY = {"book_id": "BK001", "subject": "Royalty not received",
           "description": "I haven't received any royalty for 6 months. What is going on?"}


def test_ai_classification_applied(priya, fake_llm):
    tid = priya.post("/api/tickets/", ROYALTY, format="json").data["id"]
    t = Ticket.objects.get(pk=tid)
    assert (t.category, t.priority, t.category_source, t.ai_status) == (
        "royalty_payments", "critical", "ai", "completed")
    assert t.ai_confidence == 0.9
    # Classifier prompt carries no knowledge base (cost) but does carry account hints
    call = fake_llm.calls[0]
    assert "Royalty Policy" not in call["system"]
    assert "<account_hints>" in call["user"]


def test_ai_never_overwrites_admin_override(priya, admin, fake_llm):
    tid = priya.post("/api/tickets/", ROYALTY, format="json").data["id"]
    admin.patch(f"/api/tickets/{tid}/", {"priority": "medium"}, format="json")
    classify_ticket(tid)  # e.g. a re-run
    t = Ticket.objects.get(pk=tid)
    assert t.priority == "medium" and t.priority_source == "admin"
    assert t.ai_priority == "critical"  # AI opinion still recorded for accuracy stats


def test_invalid_ai_output_falls_back(priya, fake_llm):
    fake_llm.responses["classify"] = {"category": "astrology", "priority": "urgent", "confidence": 2,
                                      "rationale": "", "summary": ""}
    tid = priya.post("/api/tickets/", ROYALTY, format="json").data["id"]
    t = Ticket.objects.get(pk=tid)
    assert t.ai_status == "failed" and t.category_source == "rules"


def test_ticket_creation_survives_ai_outage(priya, broken_llm):
    resp = priya.post("/api/tickets/", ROYALTY, format="json")
    assert resp.status_code == 201
    t = Ticket.objects.get(pk=resp.data["id"])
    assert t.ai_status == "failed"
    assert t.category == "royalty_payments" and t.priority == "critical"  # rules fallback
    assert t.events.filter(kind="ai_failed").exists()


def test_draft_uses_selected_kb_and_facts_and_is_cached(priya, admin, fake_llm):
    tid = priya.post("/api/tickets/", ROYALTY, format="json").data["id"]
    first = admin.get(f"/api/tickets/{tid}/ai-draft/").data
    assert first["source"] == "ai" and first["cached"] is False
    assert first["kb_sections"] == ["tone_guidelines", "company_overview", "royalty_policy"]

    draft_call = [c for c in fake_llm.calls if c["operation"] == "draft"][0]
    assert "Royalty Policy" in draft_call["system"]
    assert "Printing & Quality" not in draft_call["system"]   # irrelevant KB omitted
    assert "₹3,570" in draft_call["user"]                      # real figures from the dataset
    assert "Whispers of the Ganges" in draft_call["user"]

    second = admin.get(f"/api/tickets/{tid}/ai-draft/").data
    assert second["cached"] is True
    assert len([c for c in fake_llm.calls if c["operation"] == "draft"]) == 1

    # A new author message invalidates the cache
    priya.post(f"/api/tickets/{tid}/messages/", {"body": "Any update?"}, format="json")
    assert admin.get(f"/api/tickets/{tid}/ai-draft/").data["cached"] is False

    # POST forces regeneration
    admin.post(f"/api/tickets/{tid}/ai-draft/")
    assert AIDraft.objects.filter(ticket_id=tid).count() == 3


def test_draft_falls_back_to_template(priya, admin, broken_llm):
    tid = priya.post("/api/tickets/", ROYALTY, format="json").data["id"]
    resp = admin.get(f"/api/tickets/{tid}/ai-draft/")
    assert resp.status_code == 200
    assert resp.data["source"] == "template"
    assert "Hi Priya" in resp.data["body"] and "₹3,570" in resp.data["body"]


def test_circuit_breaker_stops_calls_after_repeated_failures(settings, priya, monkeypatch):
    """Exercise the real LLMClient against a failing SDK to check breaker + usage logs."""
    import anthropic

    from apps.ai.llm import LLMClient
    from apps.ai.models import AIUsageLog

    settings.AI = {**settings.AI, "PROVIDER": "anthropic", "API_KEY": "test-key", "MAX_RETRIES": 0}
    calls = {"n": 0}

    def boom(self, **kwargs):
        calls["n"] += 1
        # Build the SDK's error without its version-specific constructor.
        exc = anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
        Exception.__init__(exc, "Connection error.")
        raise exc

    monkeypatch.setattr(anthropic.resources.Messages, "create", boom)
    for _ in range(5):
        priya.post("/api/tickets/", ROYALTY, format="json")
    assert calls["n"] == 3  # breaker opened after 3 consecutive failures
    assert AIUsageLog.objects.filter(error_type="circuit_open").count() == 2
    assert Ticket.objects.filter(ai_status="failed").count() == 5


def test_gemini_circuit_breaker(settings, priya, monkeypatch):
    """Exercise real LLMClient on Gemini against failing SDK to check breaker + usage logs."""
    from google.genai.errors import ServerError
    from apps.ai.models import AIUsageLog

    settings.AI = {**settings.AI, "PROVIDER": "gemini", "API_KEY": "test-key", "MAX_RETRIES": 0}
    calls = {"n": 0}

    def boom(self, **kwargs):
        calls["n"] += 1
        exc = ServerError(500, "Server error")
        raise exc

    monkeypatch.setattr("google.genai.models.Models.generate_content", boom)
    for _ in range(5):
        priya.post("/api/tickets/", ROYALTY, format="json")
    assert calls["n"] == 3  # breaker opened after 3 consecutive failures
    assert AIUsageLog.objects.filter(error_type="circuit_open").count() == 2
    assert Ticket.objects.filter(ai_status="failed").count() == 5



def test_rules_fallback_examples():
    assert classify_by_rules("Wrong ISBN on Amazon", "The ISBN differs").priority == "high"
    assert classify_by_rules("Book unavailable", "Amazon shows currently unavailable").category == \
        Category.DISTRIBUTION
    assert classify_by_rules("Blurry pages", "Print quality is terrible, pages misaligned").category == \
        Category.PRINTING
    assert classify_by_rules("Update bio", "Can I update my author bio?").priority == "low"


def test_kb_selection_is_smaller_than_full_kb():
    for cat in Category:
        selected = kb.render_sections(kb.sections_for(cat)) + kb.render_examples(cat)
        assert len(selected) < 0.7 * kb.full_kb_char_count(), cat


def test_payout_schedule():
    s = payout_schedule(date(2026, 1, 10))
    assert s.next_payout_date == date(2026, 2, 14) and s.next_payout_covers == "Oct–Dec 2025"
    s = payout_schedule(date(2026, 3, 1))
    assert s.next_payout_date == date(2026, 5, 15)


def test_royalty_flags_edge_cases(seeded):
    never_paid = book_royalty_flags(Book.objects.get(book_id="BK005"), date(2026, 1, 10))
    assert never_paid["never_paid"] and never_paid["possibly_overdue"]
    in_production = book_royalty_flags(Book.objects.get(book_id="BK013"), date(2026, 1, 10))
    assert not any([in_production["never_paid"], in_production["possibly_overdue"]])
    small = book_royalty_flags(Book.objects.get(book_id="BK016"), date(2026, 1, 10))
    assert small["below_payout_threshold"]
    fully_paid = book_royalty_flags(Book.objects.get(book_id="BK002"), date(2026, 1, 10))
    assert fully_paid["pending_amount"] == 0 and not fully_paid["possibly_overdue"]


def test_stats_endpoint(admin, priya, fake_llm):
    tid = priya.post("/api/tickets/", ROYALTY, format="json").data["id"]
    admin.patch(f"/api/tickets/{tid}/", {"category": "general_inquiry"}, format="json")
    stats = admin.get("/api/admin/stats/").data
    assert stats["ai"]["category_override_rate"] == 1.0
    assert stats["queue"]["by_status"]["open"] == 1
