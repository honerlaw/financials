# LLM Chat Interface — Design

**Date:** 2026-05-17
**Status:** Draft — awaiting review

## Goal

Add an in-app chat interface that lets the user generate the existing
report-style analyses (spending summary, recurring expenses, spending
breakdown, cross-account cash flow) and ask free-form follow-up questions
about their transaction data, powered by an LLM via OpenRouter.

The four report styles already exist as Claude Code skills in a separate
plugin repository operating on CSV snapshots. This feature brings the same
capability into the running Flask app, against the live Plaid-synced
database.

## Scope

### In scope (v1)

- New `/chat` page in the existing Flask app
- Chat hits an LLM via OpenRouter (model swappable via env var)
- LLM uses typed Python function tools to query the read-only `Transaction` table
- Quick-action chips above the input fire pre-baked prompts for the four
  report styles; user can also type any free-form question
- Server-sent events (SSE) stream tokens, tool calls, and tool results to
  the browser as they happen
- Conversation history is held in browser memory only — no persistence

### Out of scope (deferred)

- Persistent conversations / multi-thread sidebar
- Write tools (updating categories, tagging persons, hiding transactions)
- Multi-user support
- LLM cost/usage tracking and dashboards
- Conversation history auto-summarization / context compression

## Architecture

A new `app/chat/` package, plus a chat page and small frontend JS module.
Conversation state lives entirely in the browser; the server is stateless
except for the per-request LLM↔tool loop.

```
app/chat/
  __init__.py
  tools.py         # typed Python functions + JSON schemas, query DB read-only
  openrouter.py    # thin HTTP client around OpenRouter chat/completions (SSE)
  orchestrator.py  # runs LLM↔tool loop, yields SSE events
  routes.py        # /chat page, /api/chat/stream SSE endpoint
app/templates/
  chat.html        # chat UI with quick-action chips
app/static/
  chat.js          # SSE consumer, conversation state, message rendering
```

Existing patterns (Flask blueprint, `@login_required`, `current_app.config`,
SQLAlchemy `Transaction` model) are reused; no new dependencies required
beyond an HTTP library already in the standard library (`urllib`) or a
small addition (`httpx`) for streaming — implementation plan can choose.

## Components

### Tool palette (`app/chat/tools.py`)

All tools are read-only, return JSON-serializable data, and have Pydantic
argument models that generate the JSON schema sent to OpenRouter.

| Tool | Purpose |
|---|---|
| `current_date()` | Today's date — the LLM has no real-time clock |
| `get_date_range()` | Earliest/latest transaction dates in the DB |
| `list_institutions()` | Connected banks (id, name, slug, status) |
| `query_transactions(start, end, institution_id?, category?, merchant_contains?, min_amount?, max_amount?, limit=200)` | Filtered row list, hard-capped |
| `aggregate_transactions(start, end, group_by, metric, filters?)` | `group_by`: month \| category \| merchant \| institution. `metric`: sum \| abs_sum \| count \| avg \| net |
| `find_recurring(lookback_months=6, min_occurrences=2, amount_tolerance=0.10)` | Heuristic: group by `merchant_name`, find ones recurring across N+ calendar months with similar amounts (within tolerance) |

`query_transactions` enforces a hard row cap (`CHAT_QUERY_ROW_LIMIT`,
default 200) and sets `truncated: true` in the response when hit, so the
LLM can warn the user or narrow the filter.

### OpenRouter client (`app/chat/openrouter.py`)

Thin wrapper over OpenRouter's `/chat/completions` endpoint. Supports
streaming responses, OpenAI-compatible tool calling. Reads
`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` from
`current_app.config`. Single class with a `stream(messages, tools)` method
that yields parsed events (text deltas, tool-call deltas, stop).

### Orchestrator (`app/chat/orchestrator.py`)

Runs the LLM↔tool loop. Receives the conversation message array from the
route, yields SSE events. Holds the system prompt:

> You are the financial-analysis assistant for a personal-finance app. You
> have read-only access to the user's connected bank transactions via
> tools. When the user asks a free-form question, decide which tool(s) to
> call. Format final answers as markdown with tables where helpful. Use
> `current_date()` if you need to resolve "this month", "last quarter",
> etc. Don't fabricate data — only state what tools return.

Loop invariants:

- Append each assistant message (with `tool_calls`) and tool result back
  into the message array before the next OpenRouter call
- Hard cap of `CHAT_MAX_ITERATIONS` (10) LLM↔tool rounds — beyond that,
  emit `error` and stop
- Tools execute serially in the order the LLM emitted them

### Routes (`app/chat/routes.py`)

- `GET /chat` — renders `chat.html`, gated by `@login_required`. If
  `OPENROUTER_API_KEY` is missing, the page renders with a disabled input
  and a banner: "Set `OPENROUTER_API_KEY` to enable chat."
- `POST /api/chat/stream` — gated by `@login_required`. Body:
  `{ messages: [...], model?: "..." }`. Returns
  `Content-Type: text/event-stream`. The orchestrator is iterated and each
  event is serialized as an SSE frame.

### Frontend (`templates/chat.html` + `static/chat.js`)

- Chat layout: message list, quick-action chip row, input + send
- Quick-action chips are hardcoded prompt strings in `chat.js`; clicking
  one inserts the prompt as a user message and submits
- Conversation state is a plain JS array of messages; each turn sends the
  full array to `/api/chat/stream`
- SSE consumer dispatches on event type to render text/tool chips/errors
- Tool-call chips are collapsible; closed by default once results arrive

## Quick-action prompt strings

Hardcoded in `chat.js`, inserted verbatim as user messages:

- **Spending summary** — "Give me a spending summary for the most recent
  complete calendar month: monthly totals for the last 3 months, top 10
  merchants, category breakdown (you infer categories from descriptions),
  and month-over-month % change."
- **Recurring** — "Find my recurring expenses (bills, subscriptions,
  regular transfers) across the last 6 months. Group into Bills /
  Subscriptions / Regular Transfers, show typical amount and how many
  months each appeared, and end with an estimated monthly recurring
  total."
- **Spending breakdown** — "Break down my spending by category for the
  most recent complete calendar month. Infer categories from
  descriptions. Show a table sorted by total spent descending, and list
  any transactions you couldn't confidently categorize."
- **Cross-account** — "Show me a cross-account cash flow summary for the
  most recent complete calendar month: total inflow vs outflow,
  per-institution net, spend distribution percentages, and a 3-month
  trend. Call out anything notable."

## Data flow

Per-turn lifecycle (browser already holds full conversation history):

```
Browser                       Flask /api/chat/stream      OpenRouter       DB
  |--POST {messages, model}---->|                            |              |
  |                              |--POST chat/completions ---->|              |
  |                              |   stream=true              |              |
  |                              |   (system + msgs + tools)  |              |
  |<--SSE: text { delta }--------|<--token delta--------------|              |
  |                              |<--tool_call delta----------|              |
  |<--SSE: tool_start { id,name,args }                                       |
  |                              |--validate args (Pydantic) --> if invalid: |
  |                              |                              tool_result {error,schema_hint}
  |                              |--execute tool--------------------------->|
  |                              |<--rows / aggregate---------------------- |
  |<--SSE: tool_result { id,summary,rows? }                                  |
  |                              |--POST chat/completions stream---->        |
  |                              |  (msgs + assistant tool_calls +           |
  |                              |   tool_result)                            |
  |<--SSE: text { delta }--------|<--token delta--------------|              |
  |<--SSE: done { stop_reason }--|                            |              |
```

### SSE event types

| Event | Payload | UI behavior |
|---|---|---|
| `text` | `{ delta: "..." }` | Append to current assistant bubble |
| `tool_start` | `{ id, name, args }` | Render collapsible chip "Calling `name`…" |
| `tool_result` | `{ id, summary, rows? }` | Flip chip to "Returned N rows", expandable JSON |
| `done` | `{ stop_reason }` | Mark turn complete, re-enable input |
| `error` | `{ message }` | Render red message bubble, keep history intact |

## Error handling

| Failure | Behavior |
|---|---|
| `OPENROUTER_API_KEY` missing | `/chat` renders with disabled input + setup banner |
| OpenRouter HTTP 4xx/5xx | Server emits SSE `error` with status + message; UI renders red bubble |
| Network drop mid-stream | Browser sees SSE close before `done`; shows "Connection lost — retry?" button that re-POSTs the same `messages` |
| Tool args fail Pydantic validation | Tool result `{error, schema_hint}`; LLM retries with corrected args (counts toward iteration cap) |
| Tool raises unexpectedly | Caught in orchestrator → tool result `{error: "internal: <type>"}`, traceback logged server-side; loop continues |
| Iteration cap hit | Emit `error: "max iterations reached"` then `done`; conversation remains usable |
| Query returns >200 rows | Truncate to 200, set `truncated: true` |
| Unauthenticated request to `/api/chat/stream` | 401 via existing `@login_required` |

## Testing

- **Tool tests** (`tests/chat/test_tools.py`) — seed `Institution` +
  `Transaction` fixtures, call each tool directly, assert response shapes
  and aggregation math. Primary correctness layer — these tools are the
  contract with the LLM.
- **Orchestrator tests** (`tests/chat/test_orchestrator.py`) — inject a
  fake OpenRouter client whose `stream()` replays canned event sequences
  (text → tool_call → text → done; tool-error path; iteration-cap path).
  Assert emitted SSE events and tool execution order.
- **Route test** (`tests/chat/test_routes.py`) — one end-to-end: POST to
  `/api/chat/stream` with fake LLM client wired via app config, consume
  SSE, assert event ordering and final assistant text.
- **No automated frontend tests.** Manual smoke: click each chip, type a
  free-form follow-up, force a failure path (bad API key) to see the
  error UI.

## Configuration

New env vars, all read in `app/__init__.py` and exposed via
`current_app.config`:

| Variable | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | _none_ | Required for chat; absence disables the feature, not the app |
| `OPENROUTER_MODEL` | `anthropic/claude-sonnet-4` | Override to switch model |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Lets us point at a proxy if needed |
| `CHAT_MAX_ITERATIONS` | `10` | Max LLM↔tool rounds per turn |
| `CHAT_QUERY_ROW_LIMIT` | `200` | Hard cap on `query_transactions` results |

## Open questions

None at design-time. Implementation may surface choices (HTTP library for
SSE consumption, exact Pydantic model layout, etc.) that the implementation
plan can address.
