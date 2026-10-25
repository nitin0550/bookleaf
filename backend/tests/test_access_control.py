"""RBAC: authors only ever see their own data; staff-only endpoints are protected."""
import pytest

from apps.support.models import InternalNote, Ticket

pytestmark = pytest.mark.django_db


def make_ticket(client, book_id="BK001"):
    resp = client.post("/api/tickets/", {
        "book_id": book_id, "subject": "Royalty question",
        "description": "Can you explain how my royalty was calculated this quarter?",
    }, format="json")
    assert resp.status_code == 201, resp.content
    return resp.data


def test_unauthenticated_requests_are_rejected(seeded, client):
    for url in ["/api/books/", "/api/tickets/", "/api/admin/stats/", "/api/auth/me/"]:
        resp = client.get(url)
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "not_authenticated"


def test_bad_login_returns_validation_error(seeded, client):
    resp = client.post("/api/auth/login/", {"email": "priya.sharma@email.com", "password": "nope"},
                       content_type="application/json")
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "Incorrect email or password."


def test_author_sees_only_own_books(priya):
    resp = priya.get("/api/books/")
    assert [b["book_id"] for b in resp.data["results"]] == ["BK001", "BK002"]
    assert resp.data["summary"]["total_pending"] == 3570.0
    assert priya.get("/api/books/BK003/").status_code == 404


def test_author_cannot_read_or_reply_to_other_authors_ticket(priya, rohit):
    ticket = make_ticket(rohit, "BK003")
    assert priya.get(f"/api/tickets/{ticket['id']}/").status_code == 404
    assert priya.post(f"/api/tickets/{ticket['id']}/messages/", {"body": "hi there"},
                      format="json").status_code == 404
    assert priya.get("/api/tickets/").data["count"] == 0


def test_author_cannot_file_ticket_against_someone_elses_book(priya):
    resp = priya.post("/api/tickets/", {"book_id": "BK003", "subject": "Hello there",
                                        "description": "This is long enough to pass validation."},
                      format="json")
    assert resp.status_code == 400
    assert "book_id" in resp.data["error"]["details"]


def test_author_cannot_use_staff_actions(priya):
    ticket = make_ticket(priya)
    tid = ticket["id"]
    assert priya.patch(f"/api/tickets/{tid}/", {"status": "closed"}, format="json").status_code == 403
    assert priya.get(f"/api/tickets/{tid}/notes/").status_code == 403
    assert priya.get(f"/api/tickets/{tid}/ai-draft/").status_code == 403
    assert priya.post(f"/api/tickets/{tid}/assign-to-me/").status_code == 403
    assert priya.get("/api/admin/stats/").status_code == 403
    resp = priya.post(f"/api/tickets/{tid}/messages/", {"body": "Closing", "status": "closed"}, format="json")
    assert resp.status_code == 400


def test_admin_cannot_create_ticket_as_author(admin):
    resp = admin.post("/api/tickets/", {"subject": "Hello there",
                                        "description": "This is long enough to pass validation."},
                      format="json")
    assert resp.status_code == 403


def test_internal_notes_never_reach_author(priya, admin):
    ticket = make_ticket(priya)
    admin.post(f"/api/tickets/{ticket['id']}/notes/", {"body": "Secret: check bank"}, format="json")
    assert InternalNote.objects.count() == 1
    detail = priya.get(f"/api/tickets/{ticket['id']}/")
    assert "Secret" not in str(detail.content)
    for hidden in ("internal_notes", "priority", "ai_rationale", "assigned_to", "events"):
        assert hidden not in detail.data


def test_admin_sees_all_tickets_with_context(priya, rohit, admin):
    make_ticket(priya)
    make_ticket(rohit, "BK003")
    resp = admin.get("/api/tickets/")
    assert resp.data["count"] == 2
    detail = admin.get(f"/api/tickets/{resp.data['results'][0]['id']}/")
    assert "author_context" in detail.data and detail.data["author_context"]["books"]
