#!/usr/bin/env bash
# Purpose: Sync the Dream Server repo working copy into the installed runtime
#          directory (~/dream-server by default), preserving local state
#          (.env, data/, logs/, models/, workspace/, images/, backups,
#          enabled-state of services, user-added config dirs).
# Expects: rsync available; SRC and DST directories exist.
# Provides: Idempotent file sync from repo -> install dir.
#
# Modder notes:
#   - Override paths via env: DREAM_REPO_DIR, DREAM_INSTALL_DIR
#   - --dry-run / -n          Preview changes
#   - --prune                 Enable --delete (mirror mode). DEFAULT IS OFF.
#   - --restart svc1 svc2 ... Restart services via dream-cli after sync
#
# Why no delete by default?
#   The install dir contains state that doesn't exist in the repo:
#     - Installer-created backup files (*.bak, *.bak.*, *.broken, *.bak2)
#     - Runtime state (.compose-flags, *.log, *-import.log)
#     - User-enabled services (e.g. extensions/services/langfuse/compose.yaml,
#       which lives as compose.yaml.disabled in the repo)
#     - User-added config dirs (config/sillytavern/, custom backends, etc.)
#   Even with excludes we cannot enumerate every user state — default = additive.
set -euo pipefail

SRC="${DREAM_REPO_DIR:-$HOME/DreamServer/dream-server}"
DST="${DREAM_INSTALL_DIR:-$HOME/dream-server}"

# Trailing slash matters for rsync semantics
SRC="${SRC%/}/"
DST="${DST%/}/"

DRY_RUN=()
PRUNE=()
PULL=0
FORCE_PULL=0
VERBOSE=0
AUTO_RESTART=0
RESTART_SERVICES=()
# Default: preserve per-service enabled/disabled intent across pulls.
# A user who ran `dream disable searxng` should NOT see searxng silently re-enabled
# just because the repo ships it as compose.yaml.  Conversely, a user who ran
# `dream enable langfuse` should keep langfuse enabled even though the repo ships
# it as compose.yaml.disabled.  We snapshot the pre-sync state of every service
# directory and reconcile after rsync.
PRESERVE_STATE=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|-n)
      DRY_RUN=(--dry-run)
      shift
      ;;
    --prune|--delete)
      PRUNE=(--delete)
      shift
      ;;
    --pull)
      PULL=1
      shift
      ;;
    --force-pull)
      PULL=1
      FORCE_PULL=1
      shift
      ;;
    --verbose|-v)
      VERBOSE=1
      shift
      ;;
    --auto-restart)
      AUTO_RESTART=1
      shift
      ;;
    --no-preserve-state)
      PRESERVE_STATE=0
      shift
      ;;
    --preserve-state)
      PRESERVE_STATE=1
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
Usage: $(basename "$0") [--dry-run] [--prune] [--pull] [--verbose] [--auto-restart]
                        [--no-preserve-state] [--restart svc1 svc2 ...]

Sync the repo working copy into the installed runtime directory.
Default mode is ADDITIVE (no deletes) to preserve local state.

Options:
  --dry-run, -n         Preview changes without writing
  --prune, --delete     Mirror mode: delete files in DST that are not in SRC
                        (DANGEROUS — combine with --dry-run first!)
  --pull                Run 'git pull --ff-only' in the repo first
                        (refuses to run if the working tree is dirty)
  --force-pull          Like --pull but 'git reset --hard origin/<branch>' first.
                        DESTRUCTIVE — discards uncommitted local changes.
  --verbose, -v         Show every file rsync visits (not just changes)
  --auto-restart        Auto-detect changed services and restart them via dream-cli
  --restart svc...      Restart given services after sync via dream-cli
                        (combinable with --auto-restart; explicit names always restart)
  --preserve-state      (default) Snapshot per-service enabled/disabled state in DST
                        BEFORE sync and reconcile AFTER sync, so a previously
                        disabled service stays disabled (and vice versa) across
                        repo pulls.  Updated content of compose.yaml.disabled
                        files is still applied — only the *active* filename
                        (compose.yaml vs compose.yaml.disabled) is restored.
  --no-preserve-state   Skip the snapshot/reconcile step (raw rsync behaviour;
                        repo's enable/disable defaults win).

Environment overrides:
  DREAM_REPO_DIR        (default: \$HOME/DreamServer/dream-server)
  DREAM_INSTALL_DIR     (default: \$HOME/dream-server)

Always preserved (excluded from sync, even with --prune):
  Local env:      .env  .env.local  .env.bak.*
  Runtime data:   data/  logs/  cache/  tmp/  (top-level AND nested, e.g.
                  extensions/services/qdrant/data/)
  Models/media:   models/  workspace/  images/
  Backups:        *.bak  *.bak.*  *.bak2  *.broken
  Logs:           *.log  *-import.log
  Installer:      .compose-flags  .install-state*
  Build/VCS:      .git/  node_modules/  __pycache__/  *.pyc

Per-service enable state:
  By default we no longer exclude *.disabled.  Instead we snapshot which
  services are enabled (compose.yaml) vs disabled (compose.yaml.disabled) in
  DST before sync, and restore that intent after sync.  This lets repo
  changes to compose.yaml.disabled files reach enabled services while
  preventing repo defaults from silently flipping a user's choice.
  Pass --no-preserve-state to skip the reconcile step.

Examples:
  $(basename "$0") --dry-run
  $(basename "$0") --pull --auto-restart
  $(basename "$0") --pull --restart n8n
  $(basename "$0") --prune --dry-run        # preview mirror-mode deletions
EOF
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
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

# Optional git pull in the repo before sync.
# The .git/ may be in SRC itself (monorepo dir == repo root) or one level up
# (e.g. SRC=~/DreamServer/dream-server, .git lives in ~/DreamServer).
if [[ "$PULL" -eq 1 ]]; then
  git_top=$(git -C "${SRC%/}" rev-parse --show-toplevel 2>/dev/null || true)
  if [[ -z "$git_top" ]]; then
    echo "WARN: --pull requested but $SRC is not inside a git repo — skipping" >&2
  else
    # Check for uncommitted changes (porcelain output is empty for clean trees).
    dirty=$(git -C "$git_top" status --porcelain 2>/dev/null || true)
    if [[ -n "$dirty" && "$FORCE_PULL" -ne 1 ]]; then
      echo "ERROR: Repo has uncommitted changes — refusing to pull." >&2
      echo "       Repo: $git_top" >&2
      echo >&2
      echo "$dirty" | sed 's/^/         /' >&2
      echo >&2
      echo "       Options:" >&2
      echo "         1) Commit/stash your changes:  git -C $git_top stash" >&2
      echo "         2) Discard them and pull:      $0 --force-pull ..." >&2
      echo "         3) Skip --pull entirely and just sync the working copy as-is." >&2
      exit 1
    fi

    if [[ "$FORCE_PULL" -eq 1 && -n "$dirty" ]]; then
      branch=$(git -C "$git_top" rev-parse --abbrev-ref HEAD)
      remote=$(git -C "$git_top" config "branch.${branch}.remote" 2>/dev/null || echo origin)
      echo "→ --force-pull: discarding local changes in $git_top"
      git -C "$git_top" fetch "$remote" "$branch" || {
        echo "ERROR: git fetch failed" >&2
        exit 1
      }
      git -C "$git_top" reset --hard "${remote}/${branch}" || {
        echo "ERROR: git reset --hard failed" >&2
        exit 1
      }
    else
      echo "→ git pull --ff-only in $git_top"
      git -C "$git_top" pull --ff-only || {
        echo "ERROR: git pull failed" >&2
        exit 1
      }
    fi
    echo
  fi
fi

echo "→ Syncing"
echo "  from:  $SRC"
echo "  to:    $DST"
if [[ ${#PRUNE[@]} -gt 0 ]]; then
  echo "  mode:  MIRROR (--prune: deletes extra files in destination)"
else
  echo "  mode:  ADDITIVE (no deletes — pass --prune to enable mirror mode)"
fi
[[ ${#DRY_RUN[@]} -gt 0 ]] && echo "  dry:   yes (no changes written)"
echo

# Excludes apply to BOTH the source-side traversal AND deletion logic,
# so excluded files in DST are never touched.
EXCLUDES=(
  --exclude='.env'
  --exclude='.env.local'
  --exclude='.env.bak.*'
  # Runtime data — exclude at any depth (top-level + nested service dirs like
  # extensions/services/qdrant/data/, extensions/services/n8n/data/, etc.)
  --exclude='data/'
  --exclude='**/data/'
  --exclude='logs/'
  --exclude='**/logs/'
  --exclude='cache/'
  --exclude='**/cache/'
  --exclude='tmp/'
  --exclude='**/tmp/'
  --exclude='models/'
  --exclude='workspace/'
  --exclude='images/'
  --exclude='.compose-flags'
  --exclude='.install-state'
  --exclude='.install-state.*'
  --exclude='*-import.log'
  --exclude='*.log'
  --exclude='*.bak'
  --exclude='*.bak.*'
  --exclude='*.bak2'
  --exclude='*.broken'
  --exclude='.git/'
  --exclude='node_modules/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
)

# Output mode:
#   default → -i (itemize): only changed files, with status codes
#   --verbose → -av (full file list, like before)
RSYNC_FLAGS=(-a --human-readable --itemize-changes)
[[ "$VERBOSE" -eq 1 ]] && RSYNC_FLAGS+=(-v)

# ─────────────────────────────────────────────────────────────────────────────
# Auto-restart helper (defined early so dry-run preview can call it).
# Detects which services were touched by the sync and prints them, one per line.
# Mapping:
#   extensions/services/<name>/...   → service <name>
#   config/<name>/...                → service <name> (if a manifest exists)
#   docker-compose.*.yml             → all services (warn instead, too broad)
#   .env / install-core.sh / etc.    → ignored (no service mapping)
# ─────────────────────────────────────────────────────────────────────────────
detect_changed_services() {
  local body="$1"
  local svc_dir="${DST}extensions/services"
  local stack_wide=0

  # Collect service names first, then sort/dedup, then emit warning at end.
  local names=()
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    local code path
    code="${line:0:11}"
    path="${line:12}"

    case "$code" in
      \>f*|cd+++++++++*) : ;;
      *) continue ;;
    esac

    # NOISE_REGEX (mtime-only / dir mtime-only) usually means "no real
    # change" and we filter it for the pretty-printed sync summary.  But
    # when an image-pin bump happens to keep the *exact same byte length*
    # (e.g. v1.16.3 → v1.18.0, 7 chars → 7 chars), rsync's quick-check
    # ends up classifying the just-copied compose.yaml as `>f..t......`
    # because the size matches and only the mtime differs.  Skipping
    # those would silently strand the live container on the old image
    # even though the pin was bumped.  So: keep the noise filter for
    # generic paths, but make an EXCEPTION for files that carry the
    # service contract (compose.yaml*, .env*, Dockerfile*, manifest.*)
    # under extensions/services/<sid>/ — those always trigger a restart.
    if [[ "$line" =~ $NOISE_REGEX ]]; then
      if [[ ! "$path" =~ ^extensions/services/[^/]+/(compose\..+\.yaml|compose\.yaml|Dockerfile.*|manifest\..+|\.env.*)$ ]]; then
        continue
      fi
    fi

    if [[ "$path" =~ ^docker-compose\..+\.yml$ ]]; then
      stack_wide=1
      continue
    fi

    if [[ "$path" =~ ^extensions/services/([^/]+)/ ]]; then
      names+=("${BASH_REMATCH[1]}")
      continue
    fi

    if [[ "$path" =~ ^config/([^/]+)/ ]]; then
      local name="${BASH_REMATCH[1]}"
      if [[ -f "$svc_dir/$name/manifest.yaml" ]]; then
        names+=("$name")
      fi
      continue
    fi
  done <<< "$body"

  if [[ ${#names[@]} -gt 0 ]]; then
    printf '%s\n' "${names[@]}" | sort -u
  fi

  if [[ "$stack_wide" -eq 1 ]]; then
    echo "WARN: docker-compose.*.yml changed — restart the full stack manually:" >&2
    echo "      $DST/dream-cli down && $DST/dream-cli up" >&2
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Per-service enable-state snapshot/reconcile.
#
# A service directory is one of:
#   <DST>/extensions/services/<sid>/      (built-in extensions)
#   <DST>/data/user-extensions/<sid>/     (user extensions installed via dashboard)
#
# State is one of:
#   enabled   → compose.yaml exists
#   disabled  → compose.yaml.disabled exists (and compose.yaml does not)
#   none      → neither exists yet (brand-new dir created by sync)
#
# We capture state BEFORE rsync, then re-apply it AFTER rsync.  Both files may
# briefly coexist after rsync (if the repo ships compose.yaml and DST already
# had compose.yaml.disabled, or vice versa); reconcile picks the snapshot
# variant and removes the other so the next `dream up` only sees one fragment.
# ─────────────────────────────────────────────────────────────────────────────
declare -A SVC_STATE_BEFORE=()
SVC_STATE_BASES=("${DST}extensions/services" "${DST}data/user-extensions")

snapshot_service_state() {
  local base d sid
  for base in "${SVC_STATE_BASES[@]}"; do
    [[ -d "$base" ]] || continue
    for d in "$base"/*/; do
      [[ -d "$d" ]] || continue
      sid=$(basename "$d")
      if [[ -f "$d/compose.yaml" ]]; then
        SVC_STATE_BEFORE["$base|$sid"]=enabled
      elif [[ -f "$d/compose.yaml.disabled" ]]; then
        SVC_STATE_BEFORE["$base|$sid"]=disabled
      fi
    done
  done
}

# Reconcile DST against the snapshot.  Echoes one line per service that was
# flipped back, plus the names of services that ended up DISABLED (so the
# auto-restart logic can skip them).  Sets RECONCILED_DISABLED as a global.
RECONCILED_DISABLED=()
reconcile_service_state() {
  local key base sid state d cf cfd
  RECONCILED_DISABLED=()
  for key in "${!SVC_STATE_BEFORE[@]}"; do
    base="${key%|*}"
    sid="${key#*|}"
    state="${SVC_STATE_BEFORE[$key]}"
    d="$base/$sid"
    cf="$d/compose.yaml"
    cfd="$d/compose.yaml.disabled"
    [[ -d "$d" ]] || continue
    case "$state" in
      enabled)
        if [[ -f "$cf" && -f "$cfd" ]]; then
          # Both exist: rsync wrote whichever file the repo ships.  If repo
          # ships .disabled, that file carries the FRESH content while DST's
          # compose.yaml is stale.  Promote the fresh one into the user's
          # chosen filename so they get content updates *and* keep their
          # enabled state.
          rel="${d#$DST}"; src_d="${SRC}${rel}"
          if [[ -f "$src_d/compose.yaml.disabled" && ! -f "$src_d/compose.yaml" ]]; then
            mv -f "$cfd" "$cf"
            echo "  · kept ENABLED:  $sid (promoted fresh .disabled → compose.yaml)"
          else
            # Repo ships compose.yaml (the active one was just rewritten).
            # Drop the stale .disabled marker that lingered in DST.
            rm -f "$cfd"
            echo "  · kept ENABLED:  $sid (removed stale .disabled marker)"
          fi
        elif [[ ! -f "$cf" && -f "$cfd" ]]; then
          # Repo removed compose.yaml entirely (rare, --prune mode); promote.
          mv "$cfd" "$cf"
          echo "  · restored ENABLED:  $sid"
        elif [[ ! -f "$cf" && ! -f "$cfd" ]]; then
          echo "  · WARN: $sid was enabled but compose fragment vanished after sync" >&2
        fi
        ;;
      disabled)
        if [[ -f "$cf" && -f "$cfd" ]]; then
          rel="${d#$DST}"; src_d="${SRC}${rel}"
          if [[ -f "$src_d/compose.yaml" && ! -f "$src_d/compose.yaml.disabled" ]]; then
            # Repo ships compose.yaml → that's where the FRESH content lives.
            # User wants disabled, so park the fresh content under .disabled.
            mv -f "$cf" "$cfd"
            echo "  · kept DISABLED: $sid (parked fresh compose.yaml → .disabled)"
          else
            rm -f "$cf"
            echo "  · kept DISABLED: $sid (removed stale compose.yaml)"
          fi
          RECONCILED_DISABLED+=("$sid")
        elif [[ -f "$cf" && ! -f "$cfd" ]]; then
          mv "$cf" "$cfd"
          echo "  · restored DISABLED: $sid"
          RECONCILED_DISABLED+=("$sid")
        else
          # Already disabled; nothing to do.
          RECONCILED_DISABLED+=("$sid")
        fi
        ;;
    esac
  done
}

# Snapshot now (only if state preservation is on).
if [[ "$PRESERVE_STATE" -eq 1 ]]; then
  snapshot_service_state
  if [[ ${#SVC_STATE_BEFORE[@]} -gt 0 ]]; then
    echo "→ Snapshot: ${#SVC_STATE_BEFORE[@]} service dir(s) tracked for state preservation"
    echo
  fi
fi

# Capture itemize output to compute summary
OUTPUT=$(rsync "${RSYNC_FLAGS[@]}" "${DRY_RUN[@]}" "${PRUNE[@]}" \
  "${EXCLUDES[@]}" \
  "$SRC" "$DST")

# Strip rsync's stats footer (everything after the first blank line)
OUTPUT_BODY=$(echo "$OUTPUT" | sed '/^$/,$d')

# Itemize-code legend (each code is 11 chars: YXcstpoguax):
#   >f.st......  content changed (size+time differ) → real change
#   >f+++++++++  new file
#   cd+++++++++  new directory
#   >f..tp.....  permission bit changed (e.g. exec bit) → real change
#   >f..t......  ONLY mtime differs (content identical) → noise from clone-time vs install-time
#   .d..t......  ONLY directory mtime differs           → noise
#   *deleting    file removed (only with --prune)
#
# Filter: hide pure-mtime noise unless --verbose was passed.
# rsync itemize lines look like:  ">f..t......  path/to/file"
# (11-char code, then whitespace, then filename). Don't anchor with $ — match
# the code followed by whitespace.
NOISE_REGEX='^[>.][fd]\.\.t\.\.\.\.\.\.[[:space:]]'

if [[ "$VERBOSE" -eq 1 ]]; then
    DISPLAY="$OUTPUT_BODY"
    noise_count=0
else
    DISPLAY=$(echo "$OUTPUT_BODY" | grep -Ev "$NOISE_REGEX" || true)
    noise_count=$(echo "$OUTPUT_BODY" | grep -Ec "$NOISE_REGEX" || true)
fi

if [[ -n "$DISPLAY" ]]; then
    echo "$DISPLAY"
else
    echo "  (no real content/permission changes)"
fi

# Counts
created=0
updated=0
deleted=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  case "$line" in
    \>f+++++++++*|cd+++++++++*) created=$((created+1)) ;;
    \*deleting*)  deleted=$((deleted+1)) ;;
    \>f*)
        # any file change other than pure-mtime noise counts as updated
        if [[ ! "$line" =~ $NOISE_REGEX ]]; then
            updated=$((updated+1))
        fi
        ;;
  esac
done <<< "$OUTPUT_BODY"

echo
echo "✓ Summary:  created=$created  updated=$updated  deleted=$deleted  mtime-only=$noise_count"
if [[ "$noise_count" -gt 0 && "$VERBOSE" -ne 1 ]]; then
    echo "  ($noise_count files have identical content, only timestamp differs — pass --verbose to see them)"
fi
if [[ ${#DRY_RUN[@]} -gt 0 ]]; then
  echo "  (dry-run only — re-run without --dry-run to apply)"
  if [[ "$PRESERVE_STATE" -eq 1 ]]; then
    # Predict which services would be flipped back, without touching the FS.
    flip_count=0
    for key in "${!SVC_STATE_BEFORE[@]}"; do
      base="${key%|*}"
      sid="${key#*|}"
      state="${SVC_STATE_BEFORE[$key]}"
      d="$base/$sid"
      # Look at what the SRC ships for this service.
      rel="${d#$DST}"
      src_d="${SRC}${rel}"
      [[ -d "$src_d" ]] || continue
      src_has_cf=0;  [[ -f "$src_d/compose.yaml" ]] && src_has_cf=1
      src_has_dis=0; [[ -f "$src_d/compose.yaml.disabled" ]] && src_has_dis=1
      if [[ "$state" == enabled && "$src_has_cf" -eq 0 && "$src_has_dis" -eq 1 ]]; then
        echo "    would re-enable:  $sid"
        flip_count=$((flip_count+1))
      elif [[ "$state" == disabled && "$src_has_cf" -eq 1 ]]; then
        echo "    would re-disable: $sid"
        flip_count=$((flip_count+1))
      fi
    done
    [[ "$flip_count" -gt 0 ]] && echo "  ($flip_count state flip(s) would be reconciled)"
  fi
  # Still preview which services WOULD be auto-restarted
  if [[ "$AUTO_RESTART" -eq 1 ]]; then
    echo
    echo "→ Auto-restart preview (--auto-restart):"
    detect_changed_services "$OUTPUT_BODY" | while read -r svc; do
      [[ -n "$svc" ]] && echo "    would restart: $svc"
    done
  fi
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# Apply state reconciliation BEFORE auto-restart logic so we know which
# services ended up disabled (and must be skipped by restart).
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$PRESERVE_STATE" -eq 1 && ${#SVC_STATE_BEFORE[@]} -gt 0 ]]; then
  echo
  echo "→ Reconciling per-service enable state"
  reconcile_service_state

  # Regenerate .compose-flags so docker compose picks up the right fragment set
  # on the next dream invocation.  Mirrors what cmd_enable/cmd_disable do.
  #
  # GPU_BACKEND / TIER are normally set by the installer; if not exported in
  # the current shell, fall back to the value persisted in the install's
  # `.env` file. Hardcoding `nvidia` as a default has burned operators with
  # AMD-only hosts (Halo Strix etc.) — every sync regenerated a flags file
  # pointing at docker-compose.nvidia.yml and broke the next restart with
  # "could not select device driver \"nvidia\""; see AGENT-OPERATIONS.md §1.
  _resolved_backend="${GPU_BACKEND:-}"
  _resolved_tier="${TIER:-}"
  if [[ -z "$_resolved_backend" || -z "$_resolved_tier" ]] && [[ -f "${DST}.env" ]]; then
    _resolved_backend="${_resolved_backend:-$(grep -E '^GPU_BACKEND=' "${DST}.env" | tail -1 | cut -d= -f2- | tr -d '"' || true)}"
    _resolved_tier="${_resolved_tier:-$(grep -E '^TIER=' "${DST}.env" | tail -1 | cut -d= -f2- | tr -d '"' || true)}"
  fi
  if [[ -x "${DST}scripts/resolve-compose-stack.sh" ]]; then
    "${DST}scripts/resolve-compose-stack.sh" \
      --script-dir "${DST%/}" \
      --tier "${_resolved_tier:-1}" \
      --gpu-backend "${_resolved_backend:-cpu}" \
      > "${DST}.compose-flags" 2>/dev/null \
      || rm -f "${DST}.compose-flags"
  else
    rm -f "${DST}.compose-flags"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Combine explicit + auto-detected restart targets (dedup, preserve order).
# detect_changed_services() is defined near the top of this file.
# ─────────────────────────────────────────────────────────────────────────────
ALL_RESTARTS=("${RESTART_SERVICES[@]}")
if [[ "$AUTO_RESTART" -eq 1 ]]; then
  while IFS= read -r svc; do
    [[ -z "$svc" ]] && continue
    # Skip services that ended up disabled — restarting them would error out.
    skip=0
    for dis in "${RECONCILED_DISABLED[@]}"; do
      [[ "$dis" == "$svc" ]] && skip=1 && break
    done
    [[ "$skip" -eq 1 ]] && continue
    # Skip duplicates
    for existing in "${ALL_RESTARTS[@]}"; do
      [[ "$existing" == "$svc" ]] && skip=1 && break
    done
    [[ "$skip" -eq 0 ]] && ALL_RESTARTS+=("$svc")
  done < <(detect_changed_services "$OUTPUT_BODY")
fi

if [[ ${#ALL_RESTARTS[@]} -gt 0 ]]; then
  CLI="$DST/dream-cli"
  if [[ ! -x "$CLI" ]]; then
    echo "WARN: dream-cli not found or not executable at $CLI — skipping restart." >&2
    exit 0
  fi
  echo
  echo "→ Restarting ${#ALL_RESTARTS[@]} service(s): ${ALL_RESTARTS[*]}"
  for svc in "${ALL_RESTARTS[@]}"; do
    echo "  · $svc"
    "$CLI" restart "$svc" || echo "    WARN: restart $svc failed (non-fatal)"
  done
fi

