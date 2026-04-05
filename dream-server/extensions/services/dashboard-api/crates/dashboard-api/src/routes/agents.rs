//! Agent router — /api/agents/* endpoints. Mirrors routers/agents.py.

use axum::extract::State;
use axum::Json;
use serde_json::{json, Value};

use crate::agent_monitor::get_full_agent_metrics;
use crate::state::AppState;

/// GET /api/agents/metrics — real-time agent monitoring metrics
pub async fn agent_metrics() -> Json<Value> {
    Json(get_full_agent_metrics())
}

/// GET /api/agents/cluster — cluster health status
pub async fn agent_cluster() -> Json<Value> {
    let metrics = get_full_agent_metrics();
    Json(metrics["cluster"].clone())
}

/// GET /api/agents/throughput — throughput metrics
pub async fn agent_throughput() -> Json<Value> {
    let metrics = get_full_agent_metrics();
    Json(metrics["throughput"].clone())
}

/// GET /api/agents/sessions — active agent sessions from Token Spy
pub async fn agent_sessions(State(state): State<AppState>) -> Json<Value> {
    let token_spy_url =
        std::env::var("TOKEN_SPY_URL").unwrap_or_else(|_| "http://token-spy:8080".to_string());
    let token_spy_key = std::env::var("TOKEN_SPY_API_KEY").unwrap_or_default();

    let mut req = state.http.get(format!("{token_spy_url}/api/summary"));
    if !token_spy_key.is_empty() {
        req = req.bearer_auth(&token_spy_key);
    }

    match req.send().await {
        Ok(resp) if resp.status().is_success() => {
            let data: Value = resp.json().await.unwrap_or(json!([]));
            Json(data)
        }
        _ => Json(json!([])),
    }
}

/// POST /api/agents/chat — forward chat to the configured LLM
pub async fn agent_chat(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Json<Value> {
    let message = body["message"].as_str().unwrap_or("");
    let system = body["system"].as_str();

    let llm_backend = std::env::var("LLM_BACKEND").unwrap_or_default();
    let api_prefix = if llm_backend == "lemonade" { "/api/v1" } else { "/v1" };

    let svc = match state.services.get("llama-server") {
        Some(s) => s,
        None => return Json(json!({"error": "LLM service not configured"})),
    };

    let url = format!("http://{}:{}{}/chat/completions", svc.host, svc.port, api_prefix);

    let mut messages = Vec::new();
    if let Some(sys) = system {
        messages.push(json!({"role": "system", "content": sys}));
    }
    messages.push(json!({"role": "user", "content": message}));

    let payload = json!({
        "model": "default",
        "messages": messages,
        "stream": false,
    });

    match state.http.post(&url).json(&payload).send().await {
        Ok(resp) => {
            let data: Value = resp.json().await.unwrap_or(json!({}));
            Json(data)
        }
        Err(e) => Json(json!({"error": format!("LLM request failed: {e}")})),
    }
}
