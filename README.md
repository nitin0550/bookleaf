# BookLeaf Author Support & Communication Portal

A two-sided support desk for BookLeaf Publishing. Authors check their books and royalties and raise tickets. BookLeaf staff work an urgency-sorted queue where AI triages each ticket and drafts a reply grounded in BookLeaf's policies and the author's real account data.

**Stack:** Django 5 + Django REST Framework · React 18 (Vite) + TanStack Query · PostgreSQL (SQLite locally) · Anthropic Claude Haiku

| | |
|---|---|
| Live demo | `<add your deployed URL>` |
| API docs (Swagger) | `<url>/api/docs/` · raw OpenAPI at `/api/schema/` |
| Write-up | [WRITEUP.md](WRITEUP.md) |

## Test logins

| Role | Email | Password | Good for testing |
|---|---|---|---|
| Staff | `admin@bookleaf.com` | `admin123` | Admin portal (Aisha Verma) |
| Staff | `support@bookleaf.com` | `admin123` | Second agent, for assignment |
| Author | `priya.sharma@email.com` | `author123` | Two published books, one with a pending royalty |
| Author | `sneha.kulkarni@email.com` | `author123` | Three books, one in production (Cover Design) |
| Author | `kavita.deshmukh@email.com` | `author123` | One book in Typesetting, one below the ₹1,000 payout threshold |
| Author | `ananya.reddy@email.com` | `author123` | Published but never paid a royalty |

All 10 authors from `bookleaf_sample_data.json` can log in with their email and `author123`. The login page has one-click demo buttons.

---

## 1. Running locally

You need Python 3.11+ and Node 18+.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add ANTHROPIC_API_KEY to turn on AI (optional, see §4.4)
python manage.py migrate
python manage.py seed_demo --demo-tickets
python manage.py runserver      # http://127.0.0.1:8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api to :8000)
```

Run the tests with `cd backend && pytest` (29 tests). The AI is faked in tests, so no key or network is needed.

**Single-service mode (how it deploys):** run `./build.sh`, then `cd backend && gunicorn config.wsgi`. Django serves the built React app and the API from one origin.

### Deploying

`render.yaml` is a ready-made Render blueprint (web service + Postgres). On Railway or a VPS, the build command is `./build.sh` and the start command is in `Procfile`. Set these environment variables: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DATABASE_URL` and `ANTHROPIC_API_KEY`. The seed command is idempotent and runs on every deploy.

---

## 2. Architecture

```
frontend/ (React SPA)                     backend/ (Django)
 ├─ api/client.js   fetch + error envelope ├─ config/          settings (env-driven), urls, error handler
 ├─ api/hooks.js    React Query hooks      ├─ apps/accounts/   email-login User, roles, token auth, RBAC permissions
 ├─ hooks/useLiveUpdates.js  change feed   ├─ apps/catalog/    Author, Book, seed command, royalty-cycle maths
 ├─ pages/author/*  books, tickets         ├─ apps/support/    Ticket, Message, InternalNote, Event; services; API
 └─ pages/admin/*   queue, workspace       └─ apps/ai/         LLM client, KB, prompts, triage, drafting, fallbacks
```

**Key decisions**

- **Thin views, service layer.** Views validate input and call `support/services.py` (create ticket, post message, update, add note). Each service writes an audit `TicketEvent` and bumps `updated_at`, which drives live updates. Business rules live in one place.
- **Data model.**
  - `User` (email login, `role` = author/admin) is separate from `Author`, which holds the business profile. Staff are users with no author profile.
  - `Book` mirrors the dataset. Money is stored as `Decimal`. `production_stage` and `production_progress` come from the status string, so "In Production – Cover Design" renders as step 3 of 9.
  - `Ticket` stores the **effective** category and priority with a `*_source` field (`ai`/`rules`/`admin`). It also keeps the **AI's original opinion** (`ai_category`, `ai_priority`, `ai_confidence`, `ai_rationale`) even after a staff override, so classification accuracy can be measured.
  - `InternalNote` is a **separate model** from `TicketMessage`. Author-facing serializers don't reference it at all, so a missed filter can't leak a note.
  - `priority_rank` and `sla_due_at` are stored (not computed per request), so the queue sort ("unresolved → priority → oldest") and the "past SLA" filter run as plain indexed queries.
- **RBAC.** Token auth on every route except login. `IsAdmin`/`IsAuthor` handle role checks. Each view's `get_queryset()` scopes data to the caller, so another author's ticket returns **404, not 403**: we never confirm it exists. Validation also stops authors from filing a ticket against someone else's book.
- **Errors.** Every non-2xx response uses one envelope, `{"error": {"code", "message", "details"}}`. Codes include `validation_error` (with field details), `not_authenticated`, `permission_denied`, `not_found`, `conflict` (e.g. replying to a closed ticket → 409), `rate_limited` and `server_error`. A raw exception is logged and returned as a safe `server_error` message.
- **Real-time.** The app polls a lightweight change feed. `GET /api/tickets/changes/?since=` returns only the ids that changed, plus a `server_time` cursor, every 4 s. The client refetches full data only when something changed, and pauses while the tab is hidden. In testing, an author saw an admin's reply about 3 s after it was sent, with no refresh. I chose this over WebSockets because it needs no Redis or Channels, works on any host, and 3–4 s feels live for support. The endpoint is the swap point for SSE later.
- **Deterministic facts, not LLM maths.** `catalog/royalty.py` computes the quarterly payout schedule (quarter end + 45 days), the ₹1,000 threshold, "never paid" and "possibly overdue" flags. These are passed to the model as facts. The model never does date arithmetic.
- **Attachments** are validated (≤5 MB; PNG/JPG/WEBP/PDF). They are served only through the authenticated `/api/tickets/{id}/attachment/` endpoint, never from a public `/media` URL.

---

## 3. Ticket lifecycle

1. The author submits a ticket. It is saved immediately with a **keyword-rules** category and priority, so it is never uncategorised. The request returns right away.
2. After the transaction commits, a background job asks the LLM for **triage** (category, priority, confidence, one-line rationale and a 15-word summary). The result replaces the rules values unless staff have already overridden them.
3. A staff member opens the ticket. The **AI draft** is generated, or served from cache, and prefilled into the editor, along with a suggested next status and notes for the agent ("verify bank details before sending").
4. The agent edits the draft. Any `[bracketed placeholder]` left by the model blocks sending. They then send it and set the status in the same step. The first staff reply auto-assigns the ticket and records `first_response_at` (the SLA).
5. If the author follows up on a *resolved* ticket, it reopens. Replies to a *closed* ticket are rejected with 409.

---

## 4. AI integration

### 4.1 Model choice: Claude Haiku (`claude-haiku-4-5`, configurable via `AI_MODEL`)

- Both AI tasks are short, policy-bound text jobs: classify into fixed enums, and write about 150 words in a set tone. A small, fast model does them well. A frontier model would add cost and latency without a visible quality gain.
- **Forced tool use** (`tool_choice: {type: "tool"}`) means the output always matches a JSON schema. Category and priority are enums, so there is no regex-parsing of free text. The result is still validated server-side; an invalid value is treated as a failure.
- Latency matters because the draft appears while the agent is looking at the ticket.
- Indicative cost (prices configurable via env): triage is about 900 input + 80 output tokens, and a draft is about 1,700 input + 300 output. That is **about $0.005 per ticket** for triage plus one draft. The admin stats panel shows the real 30-day token use and estimated cost from `AIUsageLog`.

### 4.2 Prompt strategy (`apps/ai/prompts.py`)

- **Triage prompt.** It contains category definitions and a priority rubric taken from the brief: ISBN errors are always high, long-unpaid royalties are critical, bio edits are low, and frustration can raise priority one level. It also carries tiny account hints, e.g. "no royalty has ever been paid for this book" or "published 470 days ago". This is why a "no royalty for months" ticket from an author who really was never paid ranks above a routine one. **No knowledge base** goes into this prompt; it doesn't need one.
- **Draft prompt.** The system prompt holds the role ("a senior member of the Author Support team… never like a generic chatbot"), BookLeaf's tone guidelines verbatim, **only the KB sections relevant to the category**, and the matching **calibration examples** from the brief.
  - The user message holds `<account_facts>`: the author, the focal book with real ₹ figures and dates, the computed next payout date, threshold and overdue notes, and the conversation so far.
  - Writing rules: acknowledge first, use real numbers, own BookLeaf's mistakes, give policy timelines (48 h, 24–48 h, 5–7 days), end with a next step, use a fixed sign-off, and use a **placeholder instead of guessing** when a fact is missing.
- **Prompt-injection hygiene.** Author text is wrapped in tags and labelled untrusted data in both prompts.
- **Prompt versioning.** `PROMPT_VERSION` is part of the draft cache key, so a prompt change never serves stale drafts.

### 4.3 Cost awareness

| Technique | Where | Effect |
|---|---|---|
| Category-scoped KB retrieval | `knowledge_base.sections_for()` | The draft prompt carries tone + overview + 1–2 relevant sections + examples. That is **59–68% smaller** than the full KB (asserted in tests). |
| No KB in triage | `CLASSIFY_SYSTEM` | Triage stays at about 900 tokens. |
| Focused account context | `context.author_facts()` | Full detail for the book in question only; one line per other book. |
| Capped history | `context.thread_text()` | The original query plus the last 6 messages, each truncated. Internal notes are never sent. |
| Draft cache | `AIDraft.context_key` | The key is a SHA-256 over prompt version, category, book, latest message and relevant book fields. Re-opening a ticket costs **0 tokens**. A new author message or a category change invalidates it. `POST /ai-draft/` forces a regeneration. |
| Draft only when needed | Admin UI | Drafts are generated automatically only when the author is waiting on us, not after our own reply. |
| `max_tokens` caps + throttles | `services.py`, DRF scopes | Triage 300, draft 900. Ticket creation is limited to 30/hour per user and draft regeneration to 60/hour. |
| Usage log | `AIUsageLog` | Every call is logged (tokens, latency, error type) and summed in `/api/admin/stats/`. |

Prompt caching is not used yet: the static prefix (about 1k tokens) is below the provider's minimum cacheable size. It becomes worthwhile once the KB grows, and the system prompt is already ordered static-first for it.

### 4.4 Graceful degradation

The LLM client (`apps/ai/llm.py`) turns *every* provider problem into a single `AIUnavailable` exception: no API key, timeout, 429, 5xx/overloaded, bad response shape or invalid enum. Callers always have a fallback:

| Failure | What happens |
|---|---|
| AI down during ticket creation | The ticket is still created instantly with the rules-based category and priority, labelled **"Rules"** in the queue. An `ai_failed` event is recorded. "Re-run AI triage" retries it later. |
| AI down when opening a ticket | The draft box is filled with a **policy template** for the category, using real account facts (pending ₹, next payout date, production stage) and `[placeholders]`. It is labelled "Template (AI unavailable)". Agents can always write manually. |
| Repeated failures | A **circuit breaker** opens after 3 consecutive failures and stops calling the provider for 60 s, so an outage doesn't add a 20 s timeout to every request. The stats panel shows "AI: Paused". |
| Rate limits / transient errors | The SDK retries with exponential backoff (`AI_MAX_RETRIES`), with a request timeout (`AI_TIMEOUT_SECONDS`). |
| No key configured | The app is fully usable on rules + templates, and the queue shows "AI: Off". |

**API key security:** the key is read only from the `ANTHROPIC_API_KEY` env var in `settings.AI`. It is used only server-side in `llm.py`, never serialised, and never sent to the browser. `.env` is git-ignored, and `.env.example` has no secrets.

---

## 5. API reference

Base path `/api`. Authenticate with `POST /auth/login/`, then send `Authorization: Token <token>`. Full schemas and a try-it console are at **`/api/docs/`**.

| Method & path | Who | Purpose |
|---|---|---|
| `POST /auth/login/` | public | `{email, password}` → `{token, user}` |
| `POST /auth/logout/` | any | Revoke the token |
| `GET /auth/me/` | any | Current user |
| `GET /books/` | author: own · staff: all (`?author=AUTH001`) | Books + (authors) royalty summary and next payout date |
| `GET /books/{book_id}/` | scoped | One book, incl. `production_progress` and `royalty_flags` |
| `GET /tickets/` | author: own · staff: all | Paginated. Filters: `status`, `category`, `priority` (comma-separated), `assigned=me\|unassigned\|<id>`, `created_after`, `created_before`, `overdue`, `awaiting_staff`, `author`, `q`. `ordering=urgency\|oldest\|newest\|updated` |
| `POST /tickets/` | author | JSON or multipart: `book_id?` (null = General / Account), `subject`, `description`, `attachment?` |
| `GET /tickets/{id}/` | scoped | Author view: thread. Staff view: + AI fields, notes, events, author context |
| `PATCH /tickets/{id}/` | staff | `status`, `category`, `priority`, `assigned_to` (category/priority = override) |
| `POST /tickets/{id}/messages/` | scoped | Public reply. Staff can also send `status` and `ai_assisted` |
| `GET/POST /tickets/{id}/notes/` | staff | Internal notes |
| `POST /tickets/{id}/assign-to-me/` | staff | Self-assign |
| `GET /tickets/{id}/ai-draft/` | staff | Cached-or-new AI draft (falls back to a template) |
| `POST /tickets/{id}/ai-draft/` | staff | Force-regenerate the draft |
| `POST /tickets/{id}/reclassify/` | staff | Re-run AI triage |
| `GET /tickets/{id}/attachment/` | scoped | Download the attachment |
| `GET /tickets/changes/?since=` | scoped | Change feed for live updates |
| `GET /admin/stats/` | staff | Queue health, AI health, override rate, token usage and cost |
| `GET /staff/` | staff | Assignable staff |
| `GET /meta/` | any | Status/category/priority enums |

Example error:

```json
HTTP 400
{"error": {"code": "validation_error", "message": "Some fields are invalid.",
           "details": {"description": ["Ensure this field has at least 20 characters."]}}}
```

---

## 6. Edge cases handled (from the sample data)

- **Books in production** (BK013 Cover Design, BK015 Typesetting) have null MRP, royalty and dates. They show a stage tracker instead of sales, and the AI is told "no sales or royalties yet because the book is not published".
- **Never-paid books** (BK005, BK010, BK016, BK018) show "Last payout: Not yet". The drafter receives a "possibly overdue — own it and escalate (48h)" note when a payout deadline has passed.
- **Below the payout threshold** (BK016, ₹850): authors see a roll-over note, and drafts explain the ₹1,000 minimum instead of promising a payout.
- **Fully paid books** (₹0 pending) render normally without warnings. An author with no tickets sees friendly empty states.
- **General / account-level tickets** carry a one-line summary of every book instead of one detailed book.

> The dataset's payout dates are from 2025. Royalty maths uses today's date by default. To make demo answers line up with the data's timeframe, set `BOOKLEAF_REFERENCE_DATE=2026-01-10`.

---

## 7. Known limitations and what I'd do next

- **Background work runs in an in-process thread** (after commit). In production it should be a Celery/RQ worker with retries and a dead-letter queue. The function body (`classify_ticket`) wouldn't change.
- **Polling, not push.** Fine at this scale. At thousands of concurrent agents I'd move the change feed to SSE backed by Postgres `LISTEN/NOTIFY` or Redis.
- **The circuit breaker uses the local-memory cache**, so it is per process. With several instances, point Django's cache at Redis.
- **KB retrieval is tag-based.** With a real 50-page KB I'd add embeddings (pgvector) behind the same `sections_for()` interface, plus provider prompt caching.
- **No email notifications.** Authors would get an email on each staff reply, and staff a digest of overdue tickets.
- **AI quality loop.** Override rates and "AI-assisted" replies are already tracked. Next: a small labelled eval set (the brief's examples plus real tickets) run in CI whenever prompts change, and an edit-distance measure between the draft and the sent reply.
- **Auth.** DRF tokens don't expire. For production: short-lived JWT or session cookies, password reset, 2FA for staff.
- Attachments use local disk, which is ephemeral on most PaaS hosts. Use S3/R2 via `django-storages`.
