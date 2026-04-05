//! Setup router — /api/setup/* endpoints. Mirrors routers/setup.py.

use axum::extract::{Path, State};
use axum::Json;
use serde_json::{json, Value};
use std::path::PathBuf;

use crate::state::AppState;

fn setup_config_dir() -> PathBuf {
    let data_dir = std::env::var("DREAM_DATA_DIR")
        .unwrap_or_else(|_| shellexpand::tilde("~/.dream-server").to_string());
    PathBuf::from(&data_dir).join("config")
}

fn personas() -> Value {
    json!({
        "general": {
            "name": "General Helper",
            "system_prompt": "You are a friendly and helpful AI assistant. You're knowledgeable, patient, and aim to be genuinely useful. Keep responses clear and conversational.",
            "icon": "\u{1F4AC}"
        },
        "coding": {
            "name": "Coding Buddy",
            "system_prompt": "You are a skilled programmer and technical assistant. You write clean, well-documented code and explain technical concepts clearly. You're precise, thorough, and love solving problems.",
            "icon": "\u{1F4BB}"
        },
        "creative": {
            "name": "Creative Writer",
            "system_prompt": "You are an imaginative creative writer and storyteller. You craft vivid descriptions, engaging narratives, and think outside the box. You're expressive and enjoy wordplay.",
            "icon": "\u{1F3A8}"
        }
    })
}

/// GET /api/setup/status — check if first-run setup is complete
pub async fn setup_status() -> Json<Value> {
    let config_dir = setup_config_dir();
    let setup_complete = config_dir.join("setup-complete").exists();
    let persona = std::fs::read_to_string(config_dir.join("persona"))
        .ok()
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "general".to_string());

    Json(json!({
        "setup_complete": setup_complete,
        "persona": persona,
        "personas": personas(),
    }))
}

/// POST /api/setup/persona — set the active persona
pub async fn set_persona(Json(body): Json<Value>) -> Json<Value> {
    let persona = body["persona"].as_str().unwrap_or("general");
    let config_dir = setup_config_dir();
    let _ = std::fs::create_dir_all(&config_dir);
    match std::fs::write(config_dir.join("persona"), persona) {
        Ok(_) => Json(json!({"status": "ok", "persona": persona})),
        Err(e) => Json(json!({"error": format!("Failed to save persona: {e}")})),
    }
}

/// POST /api/setup/complete — mark first-run setup as done
pub async fn complete_setup() -> Json<Value> {
    let config_dir = setup_config_dir();
    let _ = std::fs::create_dir_all(&config_dir);
    match std::fs::write(config_dir.join("setup-complete"), "1") {
        Ok(_) => Json(json!({"status": "ok"})),
        Err(e) => Json(json!({"error": format!("Failed to mark setup complete: {e}")})),
    }
}

/// GET /api/setup/personas — list all available personas
pub async fn list_personas() -> Json<Value> {
    let all = personas();
    let list: Vec<Value> = all
        .as_object()
        .map(|m| {
            m.iter()
                .map(|(id, data)| {
                    let mut entry = data.clone();
                    entry["id"] = json!(id);
                    entry
                })
                .collect()
        })
        .unwrap_or_default();
    Json(json!({"personas": list}))
}

/// GET /api/setup/persona/:persona_id — get details about a specific persona
pub async fn get_persona(Path(persona_id): Path<String>) -> Json<Value> {
    let all = personas();
    match all.get(&persona_id) {
        Some(data) => {
            let mut result = data.clone();
            result["id"] = json!(persona_id);
            Json(result)
        }
        None => Json(json!({"error": format!("Persona not found: {persona_id}")})),
    }
}

/// POST /api/setup/test — run diagnostic tests
pub async fn setup_test(State(state): State<AppState>) -> Json<Value> {
    // Run basic connectivity tests against configured services
    let mut results = Vec::new();
    for (sid, cfg) in state.services.iter() {
        let health_url = format!("http://{}:{}{}", cfg.host, cfg.port, cfg.health);
        let ok = state
            .http
            .get(&health_url)
            .timeout(std::time::Duration::from_secs(5))
            .send()
            .await
            .map(|r| r.status().is_success())
            .unwrap_or(false);
        results.push(json!({
            "service": sid,
            "name": cfg.name,
            "status": if ok { "pass" } else { "fail" },
        }));
    }
    let passed = results.iter().filter(|r| r["status"] == "pass").count();
    let total = results.len();
    Json(json!({
        "results": results,
        "summary": format!("{passed}/{total} services healthy"),
    }))
}

/// POST /api/setup/chat — chat with the selected persona
pub async fn setup_chat(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Json<Value> {
    let message = body["message"].as_str().unwrap_or("");
    let persona_id = body["persona"].as_str().unwrap_or("general");

    let all_personas = personas();
    let system_prompt = all_personas[persona_id]["system_prompt"]
        .as_str()
        .unwrap_or("You are a helpful assistant.");

    let llm_backend = std::env::var("LLM_BACKEND").unwrap_or_default();
    let api_prefix = if llm_backend == "lemonade" { "/api/v1" } else { "/v1" };

    let svc = match state.services.get("llama-server") {
        Some(s) => s,
        None => return Json(json!({"error": "LLM service not configured"})),
    };

    let url = format!("http://{}:{}{}/chat/completions", svc.host, svc.port, api_prefix);
    let payload = json!({
        "model": "default",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        "stream": false,
    });

    match state.http.post(&url).json(&payload).send().await {
        Ok(resp) => Json(resp.json().await.unwrap_or(json!({}))),
        Err(e) => Json(json!({"error": format!("Chat failed: {e}")})),
    }
}
