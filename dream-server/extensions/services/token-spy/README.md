# Token Spy

Authenticated LLM API proxy that captures per-turn token usage, cost, latency, and session health. It sits between your client and upstream providers (Anthropic, OpenAI, Moonshot, or self-hosted OpenAI-compatible servers), logs the request lifecycle, and relays provider responses back to the caller.

## How It Works

```
Your client --Bearer TOKEN_SPY_API_KEY--> Token Spy proxy --> Upstream API
                                              |
                                              v
                                          Metrics DB <- Dashboard
                                              ^
                                              |
                                       Session Manager
```

Point your client's base URL at Token Spy instead of the provider directly.

- Clients authenticate to Token Spy with `TOKEN_SPY_API_KEY`
- Token Spy authenticates to hosted upstream providers with `UPSTREAM_API_KEY`
- Token Spy never forwards the proxy bearer token to the upstream provider
- Local/self-hosted upstreams can run without `UPSTREAM_API_KEY` when they do not require provider auth

## Features

- **Real-time dashboard** -- session health cards, cost charts, token breakdown, cumulative cost, recent turns table
- **Session health monitoring** -- detects context bloat, recommends resets, and can auto-kill sessions exceeding configured character limits
- **Multi-provider proxying** -- Anthropic Messages API (`/v1/messages`) and OpenAI-compatible Chat Completions (`/v1/chat/completions`)
- **Persistent metrics storage** -- SQLite by default, with optional PostgreSQL-backed runtime support
- **Per-agent settings** -- configurable session limits and poll intervals, editable via dashboard or REST API
- **Local model support** -- track self-hosted models (vLLM, Ollama, llama-server) with $0 cost badges

## Standalone Usage

```bash
cd token-spy
pip install -r requirements.txt
cp .env.example .env

# Required for proxy clients
export TOKEN_SPY_API_KEY=replace-me

# Required for hosted upstream providers
export UPSTREAM_API_KEY=provider-key

AGENT_NAME=my-agent python -m uvicorn main:app --host 0.0.0.0 --port 9110
```

For local/self-hosted upstreams that do not require provider authentication, `UPSTREAM_API_KEY` can be left unset.

Open `http://localhost:9110/dashboard` to see the monitoring UI.

## Configuration

See [TOKEN-SPY-GUIDE.md](TOKEN-SPY-GUIDE.md) for all available settings and auth examples.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/dashboard` | GET | Web dashboard |
| `/api/settings` | GET/POST | Read/update settings |
| `/api/usage` | GET | Raw usage data |
| `/api/summary` | GET | Aggregated metrics by agent |
| `/api/session-status` | GET | Current session health |
| `/api/reset-session` | POST | Kill active session |
| `/token_events` | GET | SSE stream of token events |
| `/v1/messages` | POST | Authenticated Anthropic proxy |
| `/v1/chat/completions` | POST | Authenticated OpenAI-compatible proxy |

See [TOKEN-SPY-GUIDE.md](TOKEN-SPY-GUIDE.md) for full API documentation.

## Provider System

Pluggable cost calculation via provider classes:

```
providers/
  base.py       -- Abstract base class (LLMProvider)
  registry.py   -- @register_provider decorator + lookup
  anthropic.py  -- Claude models with cache-aware pricing
  openai.py     -- OpenAI-compatible (GPT, Kimi, local models)
```

Add new providers by subclassing `LLMProvider` and decorating with `@register_provider("name")`.
