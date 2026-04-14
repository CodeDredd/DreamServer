# Token Spy — System Guide & Feature Roadmap

**For: AI agents and operators using the shipped Dream Server Token Spy extension**

---

## What Is Token Spy?

Token Spy is an **authenticated API proxy** that sits between your clients and upstream LLM providers. Every API call passes through Token Spy, which logs token usage, cost, latency, and session health before relaying the upstream response back to the caller.

This shipped Dream Server extension is not a "transparent, no-auth-change" drop-in proxy. The supported model is:

- Your client points its base URL at Token Spy
- Your client authenticates to Token Spy with `TOKEN_SPY_API_KEY`
- Token Spy authenticates upstream with server-side `UPSTREAM_API_KEY` for hosted providers
- Token Spy never forwards the proxy bearer token to the provider
- Local/self-hosted upstreams may run without `UPSTREAM_API_KEY` when the provider itself does not require auth

### Architecture

```
You (client) --Bearer TOKEN_SPY_API_KEY--> Token Spy proxy --> Upstream API
                                              |
                                              v
                                          SQLite/Postgres <- Dashboard
                                              ^
                                              |
                                       Session Manager
```

### Your Proxy Ports

| Agent | Proxy Port | Dashboard |
|-------|------------|-----------|
| my-agent | `:9110` | `http://localhost:9110/dashboard` |

Each agent instance shares the same database, so any dashboard shows data for all agents.

---

## Authentication Model

### Client -> Token Spy

Use your Token Spy API key on protected endpoints:

```bash
-H "Authorization: Bearer $TOKEN_SPY_API_KEY"
```

Protected routes include:

- `/api/settings`
- `/api/usage`
- `/api/summary`
- `/api/session-status`
- `/api/reset-session`
- `/v1/messages`
- `/v1/chat/completions`
- other proxied provider routes handled by the catch-all proxy

### Token Spy -> Upstream Provider

For hosted providers, configure server-side upstream auth:

```bash
export UPSTREAM_API_KEY=provider-key
```

Token Spy injects upstream auth itself and does not forward the client bearer token to the provider.

For local/self-hosted upstreams such as a local OpenAI-compatible server, `UPSTREAM_API_KEY` can be left unset if the upstream does not require authentication.

---

## How Session Control Works

Token Spy manages context size through a **character-based session limit**.

1. On every API call, Token Spy logs `conversation_history_chars`.
2. After logging, it checks whether the request exceeds `session_char_limit`.
3. If exceeded, Token Spy can kill the largest active session file so the next turn starts fresh.
4. A separate polling loop also enforces cleanup based on configured limits.

### Why Characters Instead of Tokens?

- Character counts are available before the upstream provider responds
- The metric is provider-agnostic
- The dashboard still shows token-based metrics alongside the character budget

### Default Settings

```json
{
  "session_char_limit": 200000,
  "poll_interval_minutes": 5,
  "agents": {}
}
```

Per-agent overrides use `null` to inherit the global default.

---

## API Reference

All endpoints are available on the proxy port. Multiple instances share the same database and settings file.

### Settings

**Read current settings:**

```bash
curl http://localhost:9110/api/settings \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY"
```

**Update global session limit:**

```bash
curl -X POST http://localhost:9110/api/settings \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"session_char_limit": 150000}'
```

**Set a per-agent override:**

```bash
curl -X POST http://localhost:9110/api/settings \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"agents": {"my-agent": {"session_char_limit": 80000}}}'
```

**Clear a per-agent override:**

```bash
curl -X POST http://localhost:9110/api/settings \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"agents": {"my-agent": {"session_char_limit": null}}}'
```

**Change poll frequency:**

```bash
curl -X POST http://localhost:9110/api/settings \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"poll_interval_minutes": 1}'
```

### Monitoring

**Health check (unprotected):**

```bash
curl http://localhost:9110/health
```

**Session status:**

```bash
curl "http://localhost:9110/api/session-status?agent=my-agent" \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY"
```

**Usage data:**

```bash
curl "http://localhost:9110/api/usage?hours=24&limit=100" \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY"
```

**Summary:**

```bash
curl "http://localhost:9110/api/summary?hours=24" \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY"
```

**Manual session reset:**

```bash
curl -X POST "http://localhost:9110/api/reset-session?agent=my-agent" \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY"
```

### Proxy Usage

**Anthropic Messages API via Token Spy:**

```bash
curl http://localhost:9110/v1/messages \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-sonnet-4",
    "max_tokens": 256,
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

**OpenAI-compatible Chat Completions via Token Spy:**

```bash
curl http://localhost:9110/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN_SPY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### Dashboard

Open `http://localhost:9110/dashboard` in a browser. The dashboard shows:

- Session health cards with live status badges
- Cost per turn timeline
- History growth chart with threshold lines
- Token usage charts
- Cumulative cost timeline
- Recent turns table
- Settings panel for per-agent limits and polling intervals

---

## Rules For Safe Experimentation

**DO:**

- Use the settings API to change limits
- Monitor the dashboard after changing limits
- Test per-agent overrides before changing global limits
- Confirm current session health before and after aggressive changes

**DO NOT:**

- Edit live service code on a running instance and assume behavior is unchanged
- Reuse the Token Spy bearer token as a provider credential
- Depend on client-supplied upstream auth headers being forwarded through the proxy

---

## Feature Roadmap

### Feature 1: Model Comparison View

Side-by-side performance and cost comparison across all models. Data already exists in the database; this is primarily a dashboard feature.

### Feature 2: Latency / Response Time Chart

Timeline chart showing API response times with per-model and per-agent breakdowns.

### Feature 3: Cost Alerts / Budget Cap

Configurable spending thresholds with dashboard warnings.

### Feature 4: Session Timeline / Session History

Visual history of past sessions showing lifecycle from start to reset.

### Feature 5: Stop Reason Analytics

Breakdown of why each API call ended: natural stop, tool call, max tokens, and similar reasons.

### Feature 6: Tool Usage Tracking

Track which tools are registered and how often they appear in requests.
