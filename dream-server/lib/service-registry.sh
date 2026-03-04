#!/bin/bash
# Service Registry — loads extension manifests and provides lookup functions.
# Source this file: . "$SCRIPT_DIR/lib/service-registry.sh"

EXTENSIONS_DIR="${SCRIPT_DIR:-$(pwd)}/extensions/services"
_SR_LOADED=false
_SR_CACHE="/tmp/dream-service-registry.$$.sh"

# Associative arrays (bash 4+)
declare -A SERVICE_ALIASES      # alias → service_id
declare -A SERVICE_CONTAINERS   # service_id → container_name
declare -A SERVICE_COMPOSE      # service_id → compose file path
declare -A SERVICE_CATEGORIES   # service_id → core|recommended|optional
declare -A SERVICE_DEPENDS      # service_id → space-separated dependency IDs
declare -A SERVICE_HEALTH       # service_id → health endpoint path
declare -A SERVICE_PORTS        # service_id → external port (what the user hits on localhost)
declare -A SERVICE_PORT_ENVS    # service_id → env var name for the external port
declare -A SERVICE_NAMES        # service_id → display name
declare -A SERVICE_SETUP_HOOKS  # service_id → absolute path to setup script
declare -a SERVICE_IDS          # ordered list of all service IDs

sr_load() {
    [[ "$_SR_LOADED" == "true" ]] && return 0
    SERVICE_IDS=()

    # Single Python pass: reads ALL manifests, emits sourceable bash
    python3 - "$EXTENSIONS_DIR" <<'PYEOF' > "$_SR_CACHE"
import yaml, sys, os
from pathlib import Path

ext_dir = Path(sys.argv[1])
if not ext_dir.exists():
    sys.exit(0)

for service_dir in sorted(ext_dir.iterdir()):
    if not service_dir.is_dir():
        continue
    manifest_path = None
    for name in ("manifest.yaml", "manifest.yml", "manifest.json"):
        candidate = service_dir / name
        if candidate.exists():
            manifest_path = candidate
            break
    if not manifest_path:
        continue
    try:
        with open(manifest_path) as f:
            m = yaml.safe_load(f)
        if m.get("schema_version") != "dream.services.v1":
            continue
        s = m.get("service", {})
        sid = s.get("id", "")
        if not sid:
            continue
        aliases = s.get("aliases", [])
        container = s.get("container_name", f"dream-{sid}")
        compose_file = s.get("compose_file", "")
        category = s.get("category", "optional")
        depends = s.get("depends_on", [])

        # Resolve compose path (relative to extension dir)
        compose_path = ""
        if compose_file:
            full = service_dir / compose_file
            if full.exists():
                compose_path = str(full)

        # Emit sourceable lines
        print(f'SERVICE_IDS+=("{sid}")')
        print(f'SERVICE_ALIASES["{sid}"]="{sid}"')
        for a in aliases:
            print(f'SERVICE_ALIASES["{a}"]="{sid}"')
        print(f'SERVICE_CONTAINERS["{sid}"]="{container}"')
        print(f'SERVICE_COMPOSE["{sid}"]="{compose_path}"')
        print(f'SERVICE_CATEGORIES["{sid}"]="{category}"')
        print(f'SERVICE_DEPENDS["{sid}"]="{" ".join(depends)}"')
        health = s.get("health", "/health")
        port = s.get("external_port_default", s.get("port", 0))
        port_env = s.get("external_port_env", "")
        print(f'SERVICE_HEALTH["{sid}"]="{health}"')
        print(f'SERVICE_PORTS["{sid}"]="{port}"')
        print(f'SERVICE_PORT_ENVS["{sid}"]="{port_env}"')
        print(f'SERVICE_NAMES["{sid}"]="{s.get("name", sid)}"')
        setup_hook = s.get("setup_hook", "")
        setup_path = ""
        if setup_hook:
            full = service_dir / setup_hook
            if full.exists():
                setup_path = str(full)
        print(f'SERVICE_SETUP_HOOKS["{sid}"]="{setup_path}"')
    except Exception:
        continue
PYEOF

    # Source the generated registry (one subprocess for all manifests)
    [[ -f "$_SR_CACHE" ]] && . "$_SR_CACHE"
    rm -f "$_SR_CACHE"
    _SR_LOADED=true
}

# Resolve a user-provided name to a compose service ID
sr_resolve() {
    sr_load
    local input="$1"
    echo "${SERVICE_ALIASES[$input]:-$input}"
}

# Get container name for a service ID
sr_container() {
    sr_load
    local sid
    sid=$(sr_resolve "$1")
    echo "${SERVICE_CONTAINERS[$sid]:-dream-$sid}"
}

# Get compose fragment path for a service ID
sr_compose_file() {
    sr_load
    local sid
    sid=$(sr_resolve "$1")
    echo "${SERVICE_COMPOSE[$sid]:-}"
}

# List all service IDs
sr_list_all() {
    sr_load
    printf '%s\n' "${SERVICE_IDS[@]}"
}

# List enabled services (have compose fragments that exist)
sr_list_enabled() {
    sr_load
    for sid in "${SERVICE_IDS[@]}"; do
        local cf="${SERVICE_COMPOSE[$sid]}"
        [[ -n "$cf" && -f "$cf" ]] && echo "$sid"
    done
}

# Get display name for a service ID
sr_service_names() {
    sr_load
    for sid in "${SERVICE_IDS[@]}"; do
        printf '%s\t%s\n' "$sid" "${SERVICE_NAMES[$sid]:-$sid}"
    done
}

# Build compose -f flags for all enabled extension services
sr_compose_flags() {
    sr_load
    local flags=""
    for sid in "${SERVICE_IDS[@]}"; do
        local cf="${SERVICE_COMPOSE[$sid]}"
        [[ -n "$cf" && -f "$cf" ]] && flags="$flags -f $cf"
    done
    echo "$flags"
}
