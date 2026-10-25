import pytest
from django.core.cache import cache
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai.llm import AIUnavailable, ToolResult


@pytest.fixture(autouse=True)
def _run_on_commit_immediately(monkeypatch):
    """Tests run inside a transaction that never commits; run on_commit hooks inline."""
    monkeypatch.setattr("django.db.transaction.on_commit", lambda fn, using=None, robust=False: fn())


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.AI = {**settings.AI, "API_KEY": "", "ASYNC_CLASSIFICATION": False}
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}
    settings.BOOKLEAF_REFERENCE_DATE = "2026-01-10"
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast tests
    cache.clear()


@pytest.fixture
def seeded(db):
    call_command("seed_demo", verbosity=0)


def _client_for(email, password):
    c = APIClient()
    resp = c.post("/api/auth/login/", {"email": email, "password": password}, format="json")
    assert resp.status_code == 200, resp.content
    c.credentials(HTTP_AUTHORIZATION=f"Token {resp.data['token']}")
    return c


@pytest.fixture
def priya(seeded):  # AUTH001, books BK001/BK002
    return _client_for("priya.sharma@email.com", "author123")


@pytest.fixture
def rohit(seeded):  # AUTH002, books BK003/BK004
    return _client_for("rohit.kapoor@email.com", "author123")


@pytest.fixture
def admin(seeded):
    return _client_for("admin@bookleaf.com", "admin123")


@pytest.fixture
def admin_user(seeded):
    return User.objects.get(email="admin@bookleaf.com")


class FakeLLM:
    """Stands in for LLMClient. Set .responses[op] to a dict, or to an exception to raise."""

    model = "fake-haiku"

    def __init__(self):
        self.calls = []
        self.responses = {
            "classify": {"category": "royalty_payments", "priority": "critical", "confidence": 0.9,
                         "rationale": "Unpaid for a long time.", "summary": "Royalty never paid"},
            "draft": {"reply": "Hi Priya,\n\nThanks for flagging this. " + "Detail. " * 10
                      + "\n\nWarm regards,\nBookLeaf Author Support",
                      "suggested_status": "in_progress", "agent_notes": "Check payout history."},
        }

    def call_tool(self, *, operation, system, user, tool, max_tokens, ticket=None):
        self.calls.append({"operation": operation, "system": system, "user": user})
        resp = self.responses[operation]
        if isinstance(resp, Exception):
            raise resp
        return ToolResult(resp, self.model, 500, 80, 120)


@pytest.fixture
def fake_llm(settings, monkeypatch):
    settings.AI = {**settings.AI, "API_KEY": "test-key"}
    fake = FakeLLM()
    monkeypatch.setattr("apps.ai.services.get_client", lambda: fake)
    return fake


@pytest.fixture
def broken_llm(fake_llm):
    fake_llm.responses["classify"] = AIUnavailable("RateLimitError")
    fake_llm.responses["draft"] = AIUnavailable("APITimeoutError")
    return fake_llm
