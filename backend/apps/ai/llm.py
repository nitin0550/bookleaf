"""
Thin, provider-specific LLM client.

Everything above this module (classifier, drafter) talks to ``LLMClient`` and
only ever sees two outcomes: a ``ToolResult`` or an ``AIUnavailable``
exception. That single failure type is what makes graceful degradation simple:
callers catch it and fall back to rules/templates.

Resilience built in here:
* Request timeout + SDK-level retries with exponential backoff (429/5xx/overloaded).
* A small circuit breaker: after several consecutive failures we stop calling
  the provider for a cool-down period. During an outage this keeps ticket
  creation fast (no 20s timeout per request) and avoids burning retries.
* Every call — success or failure — is recorded in ``AIUsageLog``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.cache import cache

from .models import AIUsageLog

logger = logging.getLogger("apps.ai")

BREAKER_KEY = "ai:breaker:failures"
BREAKER_OPEN_KEY = "ai:breaker:open"
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN_SECONDS = 60


class AIUnavailable(Exception):
    """The AI could not produce a usable result. Callers must fall back."""

    def __init__(self, reason: str, *, retryable: bool = True):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


@dataclass
class ToolResult:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


def ai_enabled() -> bool:
    return bool(settings.AI.get("API_KEY"))


def breaker_is_open() -> bool:
    return bool(cache.get(BREAKER_OPEN_KEY))


def _record_failure():
    failures = (cache.get(BREAKER_KEY) or 0) + 1
    cache.set(BREAKER_KEY, failures, BREAKER_COOLDOWN_SECONDS * 5)
    if failures >= BREAKER_THRESHOLD:
        logger.warning("AI circuit breaker opened after %s consecutive failures", failures)
        cache.set(BREAKER_OPEN_KEY, True, BREAKER_COOLDOWN_SECONDS)
        cache.set(BREAKER_KEY, 0, BREAKER_COOLDOWN_SECONDS * 5)


def _record_success():
    cache.delete(BREAKER_KEY)


class LLMClient:
    """Calls the model with a single forced tool so output is always structured JSON."""

    def __init__(self):
        cfg = settings.AI
        if not cfg.get("API_KEY"):
            raise AIUnavailable("AI is not configured (ANTHROPIC_API_KEY missing).", retryable=False)
        import anthropic  # imported lazily so the app runs without the SDK configured

        self._anthropic = anthropic
        self.model = cfg["MODEL"]
        self.client = anthropic.Anthropic(
            api_key=cfg["API_KEY"],
            timeout=cfg["TIMEOUT_SECONDS"],
            max_retries=cfg["MAX_RETRIES"],
        )

    def call_tool(
        self,
        *,
        operation: str,
        system: str,
        user: str,
        tool: dict,
        max_tokens: int,
        ticket=None,
    ) -> ToolResult:
        if breaker_is_open():
            self._log(operation, ticket, success=False, error_type="circuit_open")
            raise AIUnavailable("AI temporarily paused after repeated failures; using fallback.")

        started = time.monotonic()
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
            )
        except self._anthropic.APIError as exc:  # timeouts, 429, 5xx, auth, bad request…
            latency = int((time.monotonic() - started) * 1000)
            error_type = type(exc).__name__
            logger.warning("LLM %s call failed: %s", operation, error_type)
            self._log(operation, ticket, success=False, error_type=error_type, latency_ms=latency)
            _record_failure()
            raise AIUnavailable(f"AI provider error ({error_type}).") from exc

        latency = int((time.monotonic() - started) * 1000)
        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0

        block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
        if block is None or not isinstance(block.input, dict):
            self._log(operation, ticket, success=False, error_type="no_tool_output",
                      input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency)
            _record_failure()
            raise AIUnavailable("AI returned an unexpected response shape.")

        self._log(operation, ticket, success=True, input_tokens=in_tok,
                  output_tokens=out_tok, latency_ms=latency)
        _record_success()
        return ToolResult(block.input, self.model, in_tok, out_tok, latency)

    def _log(self, operation, ticket, *, success, error_type="", input_tokens=0,
             output_tokens=0, latency_ms=0):
        try:
            AIUsageLog.objects.create(
                operation=operation, model=self.model, ticket=ticket, success=success,
                error_type=error_type, input_tokens=input_tokens, output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
        except Exception:  # logging must never break the request
            logger.exception("Failed to write AIUsageLog")


def get_client() -> LLMClient:
    """Factory used by services; tests patch this to inject a fake client."""
    return LLMClient()
