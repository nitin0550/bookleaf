# Approach: BookLeaf Author Support Portal

**What I optimised for.** The brief's real problem is that the ops team can't keep up with author queries. So I built for the person working the queue first: urgent and oldest tickets come to the top, the AI does the first-draft work, and the agent stays in control of what gets sent. The AI is assistive, never autonomous. It triages and drafts, but a human reviews and sends every reply, and every AI value can be overridden.

**What I prioritised**

1. **A ticket lifecycle that never breaks.** Ticket creation doesn't depend on the LLM. Every ticket gets an instant rules-based category and priority, and the AI refines it in the background. If the AI is down, rate-limited or unconfigured, the app degrades to rules plus policy templates. A circuit breaker stops a provider outage from slowing every request. This is tested, not just claimed.
2. **Answers that are specific and correct.** The brief asks for "actual numbers, dates, and statuses". LLMs are unreliable at date arithmetic, so the code computes the facts: next payout date (quarter end + 45 days), the ₹1,000 threshold, never-paid and possibly-overdue flags, and production stage. The model receives them as facts. It is told to leave a `[placeholder]` rather than guess, and the UI won't send a reply with an unfilled placeholder.
3. **Cost by design.** The draft prompt carries only the KB sections relevant to the ticket's category (59–68% smaller than the full KB). Triage carries no KB at all. Account context is focused on the book in question, and history is capped. Drafts are cached against a hash of their inputs, so re-opening a ticket costs nothing. Every call is logged with tokens and latency, and the admin dashboard shows 30-day cost and the AI override rate. Roughly $0.005 per ticket on Haiku.
4. **Safety in the data model.** Authors can only reach their own data: scoped querysets return 404 for anyone else's. Internal notes live in a separate table that author-facing serializers never touch. Attachments are served only through an authenticated endpoint. The API key exists only in a server-side environment variable.

**Trade-offs I made**

- **Polling over WebSockets.** A tiny change-feed endpoint polled every 4 s needs no Redis or Channels and runs on any host. Authors see replies in about 3 s. That is the right cost and complexity point for support tickets, and the endpoint is the drop-in point for SSE later.
- **An in-process background thread instead of Celery.** It keeps the deploy to one service. The task function is already isolated, so moving to a queue is a wiring change.
- **Tag-based KB retrieval instead of embeddings.** The KB is about 1.5k tokens, so embeddings would be over-engineering today. `sections_for()` is the seam where vector search would slot in.
- **A small model (Claude Haiku) with forced tool calls.** These tasks are short and policy-bound, so a small model is enough. Forced tool calls give schema-valid JSON every time, which I still validate.
- **A plain, functional UI** (hand-rolled CSS) rather than a component library. The effort went into workflow details instead: SLA countdowns, "awaiting our reply" markers, AI-vs-rules-vs-staff source labels, a production-stage tracker, and empty and edge states for in-production and unpaid books.

**How I'd evolve it into production**

- **Reliability:** a Celery/RQ worker with retries, Redis for the shared circuit breaker and cache, Postgres `LISTEN/NOTIFY` feeding SSE, S3 for attachments, Sentry and structured logs.
- **AI quality loop:** turn the brief's examples and real resolved tickets into an evaluation set that runs in CI on every prompt change. Use the override-rate and draft-vs-sent edit-distance data I already collect to tune prompts. Add the agent's final reply as a few-shot example for similar tickets.
- **Scale and retrieval:** embedding retrieval over a growing KB, provider prompt caching for the static prefix, batch re-triage during backlog spikes, and maybe auto-sending low-risk answers (e.g. metadata how-tos) with sampling-based human review.
- **Product:** email and WhatsApp notifications, real-time royalty statements per platform, macros for common replies, SLA dashboards per agent, and a feedback button on each AI draft.
- **Security:** expiring tokens or session auth, staff 2FA, audit-log export, and PII redaction before LLM calls where policy requires it.
