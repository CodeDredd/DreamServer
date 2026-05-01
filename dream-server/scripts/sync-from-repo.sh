#!/usr/bin/env bash
# Purpose: Sync the Dream Server repo working copy into the installed runtime
#          directory (~/dream-server by default), preserving local state
#          (.env, data/, logs/, models/, workspace/, images/).
# Expects: rsync available; SRC and DST directories exist.
# Provides: Idempotent file sync from repo -> install dir.
# Modder notes:
#   - Override paths via env: DREAM_REPO_DIR, DREAM_INSTALL_DIR
#   - Pass --dry-run as first arg to preview changes
#   - Pass --restart <svc> [<svc>...] after sync to restart services via dream-cli
set -euo pipefail

SRC="${DREAM_REPO_DIR:-$HOME/DreamServer/dream-server}"
DST="${DREAM_INSTALL_DIR:-$HOME/dream-server}"

# Trailing slash matters for rsync semantics
SRC="${SRC%/}/"
DST="${DST%/}/"

DRY_RUN=()
RESTART_SERVICES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|-n)
      DRY_RUN=(--dry-run)
      shift
      ;;
    --restart)
      shift
      while [[ $# -gt 0 && "$1" != --* ]]; do
        RESTART_SERVICES+=("$1")
        shift
      done
      ;;
    -h|--help)
      cat <<EOF
Usage: $(basename "$0") [--dry-run] [--restart svc1 svc2 ...]

Syncs files from the repo working copy to the installed runtime directory.

Environment overrides:
  DREAM_REPO_DIR      (default: \$HOME/DreamServer/dream-server)
  DREAM_INSTALL_DIR   (default: \$HOME/dream-server)

Excluded from sync (preserved in target):
  .env  data/  logs/  models/  workspace/  images/  .git/  node_modules/  __pycache__/

Examples:
  $(basename "$0") --dry-run
  $(basename "$0")
  $(basename "$0") --restart n8n dashboard
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "$SRC" ]]; then
  echo "ERROR: Source repo directory not found: $SRC" >&2
  exit 1
fi
if [[ ! -d "$DST" ]]; then
  echo "ERROR: Install directory not found: $DST" >&2
  exit 1
fi

command -v rsync >/dev/null 2>&1 || {
  echo "ERROR: rsync is required but not installed." >&2
  exit 1
}

echo "→ Syncing"
echo "  from: $SRC"
echo "  to:   $DST"
[[ ${#DRY_RUN[@]} -gt 0 ]] && echo "  mode: DRY RUN (no changes written)"
echo

rsync -av --delete "${DRY_RUN[@]}" \
  --exclude='.env' \
  --exclude='.env.local' \
  --exclude='data/' \
  --exclude='logs/' \
  --exclude='models/' \
  --exclude='workspace/' \
  --exclude='images/' \
  --exclude='.git/' \
  --exclude='node_modules/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  "$SRC" "$DST"

echo
echo "✓ Sync complete."

if [[ ${#DRY_RUN[@]} -gt 0 ]]; then
  echo "  (dry-run only — re-run without --dry-run to apply)"
  exit 0
fi

if [[ ${#RESTART_SERVICES[@]} -gt 0 ]]; then
  CLI="$DST/dream-cli"
  if [[ ! -x "$CLI" ]]; then
    echo "WARN: dream-cli not found or not executable at $CLI — skipping restart." >&2
    exit 0
  fi
  for svc in "${RESTART_SERVICES[@]}"; do
    echo "→ Restarting $svc"
    "$CLI" restart "$svc" || echo "WARN: restart $svc failed (non-fatal)"
  done
fi

