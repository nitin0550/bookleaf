import pytest

from apps.support.models import Source, Ticket

pytestmark = pytest.mark.django_db


def create(client, **overrides):
    payload = {"book_id": "BK001", "subject": "I have not received my royalty",
               "description": "I haven't received my royalty payment for the last quarter at all."}
    payload.update(overrides)
    return client.post("/api/tickets/", payload, format="json")


def test_ticket_created_with_rules_when_ai_not_configured(priya):
    resp = create(priya)
    assert resp.status_code == 201
    t = Ticket.objects.get(pk=resp.data["id"])
    assert t.category == "royalty_payments"
    assert t.priority == "high"
    assert t.category_source == Source.RULES
    assert t.ai_status == "disabled"
    assert t.sla_due_at is not None


def test_general_ticket_without_book(priya):
    resp = create(priya, book_id=None, subject="Can I update my author bio?",
                  description="I'd like to change the bio shown on my book pages, is that possible?")
    assert resp.status_code == 201
    assert resp.data["book"] is None
    assert Ticket.objects.get(pk=resp.data["id"]).priority == "low"


def test_validation_errors_are_descriptive(priya):
    resp = create(priya, subject="hi", description="short")
    assert resp.status_code == 400
    err = resp.data["error"]
    assert err["code"] == "validation_error"
    assert set(err["details"]) == {"subject", "description"}


def test_full_lifecycle(priya, admin):
    tid = create(priya).data["id"]

    # Admin overrides AI/rules values and assigns
    resp = admin.patch(f"/api/tickets/{tid}/", {"priority": "critical", "category": "royalty_payments"},
                       format="json")
    assert resp.data["priority"] == "critical" and resp.data["priority_source"] == "admin"
    resp = admin.post(f"/api/tickets/{tid}/assign-to-me/")
    assert resp.data["assigned_to"]["full_name"] == "Aisha Verma"

    # Admin replies -> author sees it; status moves to in_progress
    resp = admin.post(f"/api/tickets/{tid}/messages/", {"body": "We're on it.", "ai_assisted": True},
                      format="json")
    assert resp.status_code == 201
    author_view = priya.get(f"/api/tickets/{tid}/").data
    assert author_view["status"] == "in_progress"
    assert author_view["messages"][0]["sender_name"] == "Aisha · BookLeaf Support"

    # Resolve, author follows up -> reopens
    admin.post(f"/api/tickets/{tid}/messages/", {"body": "Paid today.", "status": "resolved"}, format="json")
    assert priya.get(f"/api/tickets/{tid}/").data["status"] == "resolved"
    priya.post(f"/api/tickets/{tid}/messages/", {"body": "Not received yet"}, format="json")
    t = Ticket.objects.get(pk=tid)
    assert t.status == "open" and t.awaiting_staff

    # Closed tickets reject replies with 409
    admin.patch(f"/api/tickets/{tid}/", {"status": "closed"}, format="json")
    resp = priya.post(f"/api/tickets/{tid}/messages/", {"body": "Hello?"}, format="json")
    assert resp.status_code == 409
    kinds = [e["kind"] for e in admin.get(f"/api/tickets/{tid}/").data["events"]]
    assert "priority_changed" in kinds and "status_changed" in kinds and "assigned" in kinds


def test_queue_ordering_puts_urgent_unresolved_first(priya, admin):
    low = create(priya, book_id=None, subject="Can I update my bio please",
                 description="Is it possible to change my author bio on the listings?").data["id"]
    high = create(priya).data["id"]
    admin.patch(f"/api/tickets/{high}/", {"status": "resolved"}, format="json")
    crit = create(priya, subject="Legal notice about my royalties",
                  description="I will contact my lawyer if royalties are not paid this week.").data["id"]
    ids = [t["id"] for t in admin.get("/api/tickets/").data["results"]]
    assert ids == [crit, low, high]


def test_queue_filters(priya, admin):
    create(priya)
    create(priya, book_id=None, subject="Can I update my bio please",
           description="Is it possible to change my author bio on the listings?")
    assert admin.get("/api/tickets/?priority=high").data["count"] == 1
    assert admin.get("/api/tickets/?category=general_inquiry,royalty_payments").data["count"] == 2
    assert admin.get("/api/tickets/?assigned=unassigned").data["count"] == 2
    assert admin.get("/api/tickets/?q=bio").data["count"] == 1


def test_change_feed(priya, admin):
    feed = priya.get("/api/tickets/changes/").data
    since = feed["server_time"]
    tid = create(priya).data["id"]
    changed = priya.get("/api/tickets/changes/", {"since": since}).data["changed"]
    assert [c["id"] for c in changed] == [tid]
    assert priya.get("/api/tickets/changes/", {"since": "garbage"}).status_code == 400


def test_attachment_validation(priya):
    from django.core.files.uploadedfile import SimpleUploadedFile
    bad = SimpleUploadedFile("virus.exe", b"MZ...", content_type="application/octet-stream")
    resp = priya.post("/api/tickets/", {"book_id": "BK001", "subject": "Blurry print copies",
                                        "description": "Images are blurry in my author copies.",
                                        "attachment": bad}, format="multipart")
    assert resp.status_code == 400 and "attachment" in resp.data["error"]["details"]
    ok = SimpleUploadedFile("photo.png", b"\x89PNG....", content_type="image/png")
    resp = priya.post("/api/tickets/", {"book_id": "BK001", "subject": "Blurry print copies",
                                        "description": "Images are blurry in my author copies.",
                                        "attachment": ok}, format="multipart")
    assert resp.status_code == 201 and resp.data["attachment_url"].endswith(".png")
