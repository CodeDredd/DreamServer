# AGENT OPERATIONS — Context for new AI/Copilot sessions

> Paste this into a new chat as the first message when you want the AI to
> pick up where the last session left off.  It contains everything the
> assistant needs to operate on your two boxes (Halo Strix + Open Claw on
> Pi 5) without re-discovering the layout or repeating mistakes already
> caught.

## 1. Servers

| Alias        | Host                                     | Role                                                                 |
|--------------|------------------------------------------|----------------------------------------------------------------------|
| **Halo Strix** | `sky-net@192.168.178.110`              | Primary DreamServer host (NVIDIA backend, this repo's `dream-server/`) |
| **Open Claw**  | `claw-pi5` (SSH alias in `~/.ssh/config`) | Open Claw on Pi 5 — secondary AI-agent runtime                       |

### SSH

Don't paste passwords into prompts or commit them.  Set up once on your
WSL workstation:

```bash
ssh-copy-id sky-net@192.168.178.110         # pubkey auth, no more sshpass
# or, if you must keep password auth, store the password in your shell's
# secret manager (1password CLI, pass, etc.) and export $SSHPASS at session
# start so sshpass -e picks it up.
```

The earlier sessions used `sshpass -e` with `SSHPASS` env-var set.
That keeps the password out of `ps`, history, and any committed file.
**Never** commit the password to this repo (it's effectively public).

## 2. Repo layout

```
DreamServer/                    ← meta-repo (this directory)
├── AGENT-OPERATIONS.md         ← THIS file — operator context
├── dream-server/               ← upstream Dream Server fork (most code lives here)
│   ├── dream-cli               ← all dream <subcommand> entry-points
│   ├── extensions/services/<sid>/
│   │   ├── compose.yaml         ← active = enabled
│   │   ├── compose.yaml.disabled← active = disabled (flip via dream enable/disable)
│   │   ├── Dockerfile           ← only if locally built
│   │   └── manifest.yaml
│   ├── installers/phases/08-images.sh   ← parallel image pin list
│   ├── scripts/
│   │   ├── sync-from-repo.sh           ← repo→install rsync + state preserve
│   │   ├── check-image-updates.py      ← dream check-image-updates
│   │   └── audit-extensions.py         ← dream audit
│   └── docs/
│       ├── IMAGE-UPDATES.md
│       ├── ADR-IMAGE-TAG-PINNING.md
│       └── …
├── installer/                  ← Tauri dashboard installer (separate project)
└── resources/                  ← reference material (cookbooks, blogs, frameworks)
```

The **Halo Strix** has two parallel paths:

* `~/DreamServer/`            → git working copy, `git pull` lives here
* `~/dream-server/`           → install dir; runtime state, `.env`, `data/`,
                                user-flipped `compose.yaml.disabled` markers

`dream sync --pull` reconciles them (see §5).

## 3. Active service inventory (Halo Strix)

Last verified state (re-run `dream status` to refresh):

| Service           | Image                                                          | Notes                                  |
|-------------------|----------------------------------------------------------------|----------------------------------------|
| qdrant            | `qdrant/qdrant:v1.18.0`                                        | Has live data: `finance_assets`        |
| n8n               | `n8nio/n8n:2.20.7`                                             | Workflow engine                        |
| searxng           | `searxng/searxng:2026.5.13-8e5aa9d39`                         |                                        |
| embeddings        | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.3`      | TEI on CPU                             |
| whisper           | `ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cpu`                  | RC pin — no stable tag upstream        |
| tts               | `ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.4`                     |                                        |
| **finance-vector** | locally built `dream-server/finance-vector:0.1.0`              | Daily seeder, port 8095, see service README |
| litellm, langfuse, hermes, perplexica, comfyui, dream-proxy, hermes-proxy, privacy-shield, token-spy, tailscale, dashboard, dashboard-api, webui, llama-server | various | core stack         |

Disabled-by-user (must stay disabled across syncs): `ape`, `dreamforge`,
`openclaw`, `vikunja`.

## 4. Daily commands

```bash
# Show every container + its health
ssh sky-net@192.168.178.110 'dream status'

# Tail logs for one service
ssh sky-net@192.168.178.110 'dream logs n8n'

# Restart one service after manual config tweak
ssh sky-net@192.168.178.110 'dream restart qdrant'

# Are any image pins stale?
ssh sky-net@192.168.178.110 'dream check-image-updates'

# Full doctor
ssh sky-net@192.168.178.110 'dream doctor'
```

## 5. Edit → ship → roll out

The repo is a public Git remote; the Halo always pulls from `main`.

```bash
# On workstation
$EDITOR <files>
git commit -m "scope(svc): what changed"
git push origin main

# On Halo Strix
ssh sky-net@192.168.178.110 'dream sync --pull --auto-restart'
```

What `dream sync --pull --auto-restart` does, in order:

1. `git pull --ff-only` in `~/DreamServer`
2. **Snapshot** every service's enabled/disabled state in `~/dream-server`
   (`extensions/services/<sid>/` and `data/user-extensions/<sid>/`)
3. rsync repo → install (additive by default, no deletes)
4. **Reconcile** state: any service the user had disabled stays
   disabled (and gets fresh content under `.disabled`); any service
   the user had enabled stays enabled (and gets the fresh repo content
   even if the repo ships it as `.disabled`)
5. Regenerate `.compose-flags`
6. Auto-detect changed services (now **also** triggers on
   "mtime-only" changes for contract files — `compose*.yaml`,
   `Dockerfile*`, `manifest.*`, `.env*` — to catch byte-identical pin
   bumps that rsync's quick-check otherwise misclassifies as noise)
7. `dream restart` each, **skipping** services that ended up disabled

For a one-off rollout where you only want the auto-restart:
`dream sync --pull --auto-restart --dry-run` first to preview.

## 6. Image-pin bump procedure

```bash
# 1. See what's stale
dream check-image-updates

# 2. For each bump, edit BOTH:
#    extensions/services/<svc>/compose.yaml         (image: line)
#    installers/phases/08-images.sh                 (PULL_LIST entry)
# Some compose files have a comment block at the image: line documenting
# the bump procedure; update the version in the comment too.

# 3. Verify
dream check-image-updates -s <svc>

# 4. Ship & roll out
git commit -am "chore(<svc>): bump to <tag>"
git push
ssh sky-net@192.168.178.110 'dream sync --pull --auto-restart'
```

For containers with **live data** (qdrant, langfuse-postgres,
n8n, finance-vector seeder) you can snapshot before bumping if
the upstream changelog mentions storage migrations:

```bash
ssh sky-net@192.168.178.110 'KEY=$(grep ^QDRANT_API_KEY= ~/dream-server/.env | cut -d= -f2-) && \
  curl -fsS -X POST -H "api-key: $KEY" \
    http://127.0.0.1:6333/collections/finance_assets/snapshots'
```

## 7. Things that bit us before — read these once

* **Sync silently flipped service intent.** Before `feat(sync): preserve
  per-service enabled/disabled intent across pulls`, every pull
  re-enabled disabled services and never updated content of
  user-enabled-from-`.disabled` services.  Now both directions are
  reconciled; opt-out via `--no-preserve-state`.

* **Auto-restart missed byte-identical pin bumps.** A bump from
  `qdrant:v1.16.3` → `v1.18.0` (both 7 chars after the colon) made
  rsync classify the freshly-copied compose.yaml as `>f..t......`
  (mtime-only) and skip auto-restart.  Fix: contract files
  (`compose*.yaml`, `Dockerfile*`, `manifest.*`, `.env*`) under
  `extensions/services/<sid>/` always trigger restart.

* **Yahoo Finance throttles after a few hundred unauthenticated
  calls.** finance-vector's seeder uses the NASDAQ screener API as
  primary source for stocks (one HTTP call returns all US-listed
  symbols with marketCap, sector, country); yfinance/Wikipedia is the
  documented fallback.  See `extensions/services/finance-vector/app/seeder.py`.

* **n8n workflows reference env-vars.** Anything a workflow's Code/HTTP
  node needs via `$env.NAME` must be exposed in
  `extensions/services/n8n/compose.yaml` under `environment:`.
  Currently exposed: `VIKUNJA_API_TOKEN`, `OPENCLAW_TOKEN`,
  `GITHUB_TOKEN`, `AGENT_*`, `FINANCE_VECTOR_TOKEN`, `N8N_*`,
  `WEBHOOK_URL`, `GENERIC_TIMEZONE`.

* **searxng config dir has GID conflicts with rsync.** rsync emits a
  benign `chgrp … failed: Operation not permitted` for
  `~/dream-server/config/searxng/`; the container creates files with
  its own UID/GID.  One-off fix:
  `sudo chgrp -R sky-net ~/dream-server/config/searxng/`.  Not blocking.

## 8. Repo invariants — keep these true

* `extensions/services/<sid>/compose.yaml` and the matching
  `installers/phases/08-images.sh::PULL_LIST` entry pin the **same**
  image:tag.  `dream check-image-updates` will report drift between
  them as two separate rows (`<svc>` and `installer:<svc>`).

* Image bumps go to commit messages with `chore(<svc>): bump …`,
  feature work goes to `feat(<svc>): …`, bug fixes to `fix(<svc>): …`.

* Storage volumes for stateful services live under
  `~/dream-server/data/<sid>/` and are **never** synced.

* User-enabled services on Halo Strix that the repo ships disabled:
  `langfuse`.  Don't undo this in the repo without coordinating with
  the operator.

## 9. When in doubt

* `dream-server/CLAUDE.md` and `dream-server/CONTRIBUTING.md` — upstream
  conventions for the dream-server project itself.
* `dream-server/docs/IMAGE-UPDATES.md` — how the version checker
  classifies tags.
* `dream-server/docs/ADR-IMAGE-TAG-PINNING.md` — when to use
  `@sha256:` digests vs tag pins.
* `dream-server/extensions/services/<sid>/README.md` — per-service
  details (most have one; finance-vector definitely does).

## 10. Quick-paste prompt for new sessions

> I'm working on the DreamServer fork at
> `~/PhpstormProjects/codedredd/DreamServer`.  Read
> `AGENT-OPERATIONS.md` for the operator context (servers, repo
> layout, daily commands, sync semantics, things that bit us).
> SSH to the Halo Strix is `sky-net@192.168.178.110` and I have
> `SSHPASS` exported.  Pi 5 is the `claw-pi5` ssh alias.

