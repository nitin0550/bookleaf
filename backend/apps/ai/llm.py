"""
Provider-pluggable LLM client supporting Google AI Studio (Gemini) and Anthropic (Claude).

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

import json
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
    cache.delete(BREAKER_OPEN_KEY)


def _parse_json_payload(text: str) -> dict:
    cleaned = text.strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    if "```" in cleaned:
        lines = cleaned.splitlines()
        filtered = [line for line in lines if not line.strip().startswith("```")]
        try:
            data = json.loads("\n".join(filtered).strip())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        snippet = cleaned[first_brace : last_brace + 1]
        data = json.loads(snippet)
        if isinstance(data, dict):
            return data

    raise json.JSONDecodeError("No valid JSON object found", text, 0)


class LLMClient:
    """Calls the model with structured output matching schema."""

    def __init__(self):
        cfg = settings.AI
        self.provider = str(cfg.get("PROVIDER", "gemini")).lower()
        self.api_key = cfg.get("API_KEY", "")
        model = cfg.get("MODEL") or ("gemini-3.5-flash-lite" if self.provider == "gemini" else "claude-haiku-4-5")
        if self.provider == "gemini" and model in (
            "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash",
            "gemini-1.5-flash", "gemini-2.5-flash-lite",
        ):
            model = "gemini-3.5-flash-lite"
        self.model = model
        self.timeout = cfg.get("TIMEOUT_SECONDS", 25)
        self.max_retries = cfg.get("MAX_RETRIES", 2)

        if not self.api_key:
            key_name = "GEMINI_API_KEY" if self.provider == "gemini" else "ANTHROPIC_API_KEY"
            raise AIUnavailable(f"AI is not configured ({key_name} missing).", retryable=False)

        if self.provider == "gemini":
            from google import genai
            self._genai = genai
            self.client = genai.Client(api_key=self.api_key)
        else:
            import anthropic
            self._anthropic = anthropic
            self.client = anthropic.Anthropic(
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=self.max_retries,
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

        if self.provider == "gemini":
            return self._call_gemini(
                operation=operation,
                system=system,
                user=user,
                tool=tool,
                max_tokens=max_tokens,
                ticket=ticket,
                started=started,
            )
        else:
            return self._call_anthropic(
                operation=operation,
                system=system,
                user=user,
                tool=tool,
                max_tokens=max_tokens,
                ticket=ticket,
                started=started,
            )

    def _call_gemini(
        self,
        *,
        operation: str,
        system: str,
        user: str,
        tool: dict,
        max_tokens: int,
        ticket,
        started: float,
    ) -> ToolResult:
        from google.genai import types
        from google.genai.errors import APIError

        try:
            config = types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=tool["input_schema"],
                max_output_tokens=max_tokens,
            )
            response = self.client.models.generate_content(
                model=self.model,
                contents=user,
                config=config,
            )
        except APIError as exc:
            latency = int((time.monotonic() - started) * 1000)
            error_type = type(exc).__name__
            logger.warning("Gemini %s call failed: %s", operation, error_type)
            self._log(operation, ticket, success=False, error_type=error_type, latency_ms=latency)
            _record_failure()
            raise AIUnavailable(f"AI provider error ({error_type}).") from exc
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            error_type = type(exc).__name__
            logger.warning("Gemini %s call unexpected error: %s", operation, error_type)
            self._log(operation, ticket, success=False, error_type=error_type, latency_ms=latency)
            _record_failure()
            raise AIUnavailable(f"AI provider error ({error_type}).") from exc

        latency = int((time.monotonic() - started) * 1000)
        text = (response.text or "").strip()
        if not text:
            self._log(operation, ticket, success=False, error_type="empty_output", latency_ms=latency)
            _record_failure()
            raise AIUnavailable("AI returned an empty response.")

        try:
            data = _parse_json_payload(text)
        except json.JSONDecodeError as exc:
            self._log(operation, ticket, success=False, error_type="invalid_json", latency_ms=latency)
            _record_failure()
            raise AIUnavailable("AI returned invalid JSON.") from exc
        except Exception as exc:
            self._log(operation, ticket, success=False, error_type="invalid_shape", latency_ms=latency)
            _record_failure()
            raise AIUnavailable("AI returned an unexpected response shape.") from exc

        usage = getattr(response, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", 0) or 0
        out_tok = getattr(usage, "candidates_token_count", 0) or 0

        self._log(operation, ticket, success=True, input_tokens=in_tok,
                  output_tokens=out_tok, latency_ms=latency)
        _record_success()
        return ToolResult(data, self.model, in_tok, out_tok, latency)

    def _call_anthropic(
        self,
        *,
        operation: str,
        system: str,
        user: str,
        tool: dict,
        max_tokens: int,
        ticket,
        started: float,
    ) -> ToolResult:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
            )
        except self._anthropic.APIError as exc:
            latency = int((time.monotonic() - started) * 1000)
            error_type = type(exc).__name__
            logger.warning("Anthropic %s call failed: %s", operation, error_type)
            self._log(operation, ticket, success=False, error_type=error_type, latency_ms=latency)
            _record_failure()
            raise AIUnavailable(f"AI provider error ({error_type}).") from exc
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            error_type = type(exc).__name__
            logger.warning("Anthropic %s call unexpected error: %s", operation, error_type)
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
