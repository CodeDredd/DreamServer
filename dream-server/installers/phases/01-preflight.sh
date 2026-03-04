#!/bin/bash
# ============================================================================
# Dream Server Installer — Phase 01: Pre-flight Checks
# ============================================================================
# Part of: installers/phases/
# Purpose: Root/OS/tools checks, existing installation check
#
# Expects: SCRIPT_DIR, INSTALL_DIR, LOG_FILE, INTERACTIVE, DRY_RUN, FORCE,
#           show_phase(), ai(), ai_ok(), signal(), log(), warn(), error()
# Provides: OS sourced from /etc/os-release, OPTIONAL_TOOLS_MISSING
#
# Modder notes:
#   Add new pre-flight checks (e.g., kernel version) here.
# ============================================================================

show_phase 1 6 "Pre-flight Checks" "~30 seconds"
ai "I'm scanning your system for required components..."

# Root check
if [[ $EUID -eq 0 ]]; then
    error "Do not run as root. Run as regular user with sudo access."
fi

# OS check
if [[ ! -f /etc/os-release ]]; then
    error "Unsupported OS. This installer requires Linux."
fi

source /etc/os-release
log "Detected OS: $PRETTY_NAME"

# Check for required tools
if ! command -v curl &> /dev/null; then
    error "curl is required but not installed. Install with: sudo apt install curl"
fi
log "curl: $(curl --version | head -1)"

# Check optional tools (warn but don't fail)
OPTIONAL_TOOLS_MISSING=""
if ! command -v jq &> /dev/null; then
    OPTIONAL_TOOLS_MISSING="$OPTIONAL_TOOLS_MISSING jq"
fi
if ! command -v rsync &> /dev/null; then
    OPTIONAL_TOOLS_MISSING="$OPTIONAL_TOOLS_MISSING rsync"
fi
if [[ -n "$OPTIONAL_TOOLS_MISSING" ]]; then
    warn "Optional tools missing:$OPTIONAL_TOOLS_MISSING"
    echo "  These are needed for update/backup scripts. Install with:"
    echo "  sudo apt install$OPTIONAL_TOOLS_MISSING"
fi

# Check source files exist
if [[ ! -f "$SCRIPT_DIR/docker-compose.yml" ]] && [[ ! -f "$SCRIPT_DIR/docker-compose.base.yml" ]]; then
    error "No compose files found in $SCRIPT_DIR. Please run from the dream-server directory."
fi

# Check for existing installation
if [[ -d "$INSTALL_DIR" && "$FORCE" != "true" ]]; then
    if $INTERACTIVE && ! $DRY_RUN; then
        warn "Existing installation found at $INSTALL_DIR"
        read -p "  Overwrite and start fresh? [y/N] " -r
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log "User chose to overwrite existing installation"
            FORCE=true
        else
            log "User chose not to overwrite. Exiting."
            exit 0
        fi
    else
        error "Installation already exists at $INSTALL_DIR. Use --force to overwrite."
    fi
fi

ai_ok "Pre-flight checks passed."
signal "No cloud dependencies required for core operation."
