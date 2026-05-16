#!/usr/bin/env bash
# Bulk-import every workflow JSON from config/n8n into the running dream-n8n
# container and (optionally) activate it.
#
# Why this exists:
#   The compose mount /home/node/workflows is read-only convenience. n8n itself
#   does NOT auto-import JSON files at startup — it boots from its own SQLite
#   DB under /home/node/.n8n. Without this script, fresh workflows added to
#   config/n8n/*.json never appear in the n8n UI.
#
# Requirements on the workflow JSON:
#   - must contain a top-level "id" (string) — n8n CLI rejects imports without
#   - must NOT contain a non-empty "tags" array unless the tags already exist
#     in n8n's DB (CLI does not auto-create them, fails with
#     "SQLITE_CONSTRAINT: NOT NULL workflows_tags.tagId")
#
# Usage:
#   ./scripts/n8n-import-workflows.sh                 # import all, do not activate
#   ./scripts/n8n-import-workflows.sh --activate      # import + activate + restart n8n
#   ./scripts/n8n-import-workflows.sh path/to/wf.json # import a single file
set -euo pipefail

CONTAINER="${N8N_CONTAINER:-dream-n8n}"
WORKFLOW_DIR="${WORKFLOW_DIR:-config/n8n}"
ACTIVATE=0
FILES=()

for arg in "$@"; do
  case "$arg" in
    --activate) ACTIVATE=1 ;;
    -h|--help)
      sed -n '2,25p' "$0"
      exit 0 ;;
    *) FILES+=("$arg") ;;
  esac
done

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "✗ container '$CONTAINER' not found (is n8n running?)" >&2
  exit 1
fi

if [ "${#FILES[@]}" -eq 0 ]; then
  shopt -s nullglob
  for f in "$WORKFLOW_DIR"/*.json; do
    # skip catalog.json (manifest, not a workflow)
    [ "$(basename "$f")" = "catalog.json" ] && continue
    FILES+=("$f")
  done
fi

[ "${#FILES[@]}" -gt 0 ] || { echo "no workflow JSONs found"; exit 0; }

imported=()
skipped=()
failed=()

for f in "${FILES[@]}"; do
  base="$(basename "$f")"
  # validate required fields
  if ! python3 -c "import json,sys; d=json.load(open('$f')); sys.exit(0 if 'id' in d else 1)" 2>/dev/null; then
    echo "⊝ $base — missing top-level 'id', skipped"
    skipped+=("$base")
    continue
  fi
  wid="$(python3 -c "import json;print(json.load(open('$f'))['id'])")"
  out="$(docker exec "$CONTAINER" n8n import:workflow --input="/home/node/workflows/$base" 2>&1 | grep -v Deprecation || true)"
  if echo "$out" | grep -q "Successfully imported"; then
    echo "✓ $base ($wid)"
    imported+=("$wid")
  else
    echo "✗ $base — $(echo "$out" | tail -1)"
    failed+=("$base")
  fi
done

if [ "$ACTIVATE" -eq 1 ] && [ "${#imported[@]}" -gt 0 ]; then
  for wid in "${imported[@]}"; do
    docker exec "$CONTAINER" n8n update:workflow --id="$wid" --active=true >/dev/null 2>&1 || true
  done
  echo "→ restarting $CONTAINER to apply activation…"
  docker restart "$CONTAINER" >/dev/null
  sleep 5
  echo "→ active workflows:"
  docker exec "$CONTAINER" n8n list:workflow --active=true 2>&1 | grep -v Deprecation
fi

echo
echo "imported=${#imported[@]}  skipped=${#skipped[@]}  failed=${#failed[@]}"
[ "${#failed[@]}" -eq 0 ]

