//! Simulation summary validator — validates installer simulation output.
//! Mirrors scripts/validate-sim-summary.py.

use anyhow::{Context, Result};
use serde_json::Value;

pub fn run(file: &str) -> Result<()> {
    let text = std::fs::read_to_string(file)
        .with_context(|| format!("Reading simulation summary: {file}"))?;

    let summary: Value = serde_json::from_str(&text)
        .with_context(|| "Parsing simulation summary JSON")?;

    let mut errors: Vec<String> = Vec::new();
    let mut warnings: Vec<String> = Vec::new();

    // Validate required top-level fields
    for field in ["platform", "gpu_backend", "tier", "services", "phases"] {
        if summary.get(field).is_none() {
            errors.push(format!("Missing required field: {field}"));
        }
    }

    // Validate services
    if let Some(services) = summary.get("services").and_then(|s| s.as_array()) {
        if services.is_empty() {
            warnings.push("No services in summary".to_string());
        }
        for (i, svc) in services.iter().enumerate() {
            if svc["id"].as_str().is_none() {
                errors.push(format!("services[{i}].id is missing"));
            }
            if svc["status"].as_str().is_none() {
                errors.push(format!("services[{i}].status is missing"));
            }
        }
    }

    // Validate phases
    if let Some(phases) = summary.get("phases").and_then(|p| p.as_array()) {
        let mut prev_phase = 0;
        for (i, phase) in phases.iter().enumerate() {
            let num = phase["phase"].as_u64().unwrap_or(0);
            if num <= prev_phase && i > 0 {
                warnings.push(format!("Phase order issue at index {i}: phase {num} <= previous {prev_phase}"));
            }
            prev_phase = num;

            if phase["status"].as_str().is_none() {
                errors.push(format!("phases[{i}].status is missing"));
            }
        }
    }

    // Validate platform
    if let Some(platform) = summary["platform"].as_str() {
        let valid = ["linux-nvidia", "linux-amd", "macos", "wsl"];
        if !valid.contains(&platform) {
            warnings.push(format!("Unexpected platform: {platform}"));
        }
    }

    // Report
    println!("Simulation Summary Validation: {file}");
    if errors.is_empty() && warnings.is_empty() {
        println!("  PASS - All checks passed");
        return Ok(());
    }

    if !warnings.is_empty() {
        println!("\n  Warnings:");
        for w in &warnings {
            println!("    - {w}");
        }
    }

    if !errors.is_empty() {
        println!("\n  Errors:");
        for e in &errors {
            println!("    - {e}");
        }
        std::process::exit(1);
    }

    Ok(())
}
