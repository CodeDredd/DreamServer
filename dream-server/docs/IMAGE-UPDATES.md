# Image Update Checks

`dream check-image-updates` walks every `image:` pin in the repo, queries
the relevant Docker Hub / GHCR registries, and tells you which pins have
a newer stable tag available — without ever touching the live containers.

```
dream check-image-updates             # report
dream check-image-updates --json      # machine-readable
dream check-image-updates --strict    # exit 1 if any bump exists (CI gate)
dream check-image-updates -s n8n      # one service only
```

## Where pins are read from

| Source                                            | Counts as           |
|---------------------------------------------------|---------------------|
| `extensions/services/*/compose*.yaml`             | one pin per file    |
| `installers/phases/08-images.sh` (`PULL_LIST+=…`) | `installer:<name>`  |

`compose.yaml.disabled` files are intentionally skipped — those are the
inactive defaults shipped by the repo and aren't user-facing pins.

`${VAR:-default}` env-var defaults inside an image string are resolved
to the default value, so e.g.
`${WHISPER_IMAGE:-ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cpu}` is
checked as `ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cpu`.

## Output buckets

* **Available bumps** — a strictly higher tag of the same family exists
  upstream and is not a prerelease / mutable tag.  Action item.
* **Up to date** — your pin is the highest non-prerelease tag in its
  family that we observed.
* **Unchecked** — the tool can't make a confident recommendation.
  Reasons appear in the per-row note:
    * tag does not match a known family (custom, calver-only, GA-suffix
      we don't model yet) → manual review
    * pinned by digest (`@sha256:…`) → intentional, see
      [`ADR-IMAGE-TAG-PINNING.md`](./ADR-IMAGE-TAG-PINNING.md)
    * registry has more tags than `--max-pages-ghcr` and the highest tag
      we observed ranks BELOW the current pin (open-webui, llama.cpp
      and other repos with tens of thousands of CI build tags) → bump
      `--max-pages-ghcr` and re-run, or check upstream by hand

## Tag families

The parser ranks tags only inside a family.  Variant prefixes
(`cpu`/`cuda`, `server`/`server-cuda`, `alpine`/`bookworm`,
`stable`/`release`) are locked to the current pin's variant — we
will never propose `cpu-1.9.3 → cuda-12.4.1` or `2.8.4-alpine → 2.8.4-bookworm`.

| Family name           | Example                       | Used by                                |
|-----------------------|-------------------------------|----------------------------------------|
| `prefixed-semver`     | `cpu-1.9.3`                   | TEI (huggingface text-embeddings)      |
| `prefixed-build`      | `server-b9144`                | llama.cpp                              |
| `v-semver`            | `v1.18.0`                     | qdrant, kokoro, n8n-bare-v, dreamforge |
| `semver`              | `2.20.7`                      | n8n                                    |
| `semver-suffixed`     | `2.8.4-alpine`                | caddy                                  |
| `semver-short-suffixed` | `17.9-alpine`               | postgres                               |
| `v-semver-suffixed`   | `v1.81.3-stable`              | litellm                                |
| `v-semver-short`      | `v0.2`                        | comfyui forks                          |
| `calver`              | `2026.5.13-8e5aa9d39`         | searxng, openclaw                      |

Tags that match `latest`, `*-master*`, `*-rc.*`, `*-alpha.*`, `*-beta.*`,
`*-pre.*`, `*nightly*`, `*-dev*`, `*-canary*`, `*-edge*`, `*-snapshot*`,
or `sha-*` are never proposed as bumps.

To add a new family for an image we don't recognise:

1. Open `scripts/check-image-updates.py`
2. Add a `TagFamily(name, regex, sort_key)` entry to `TAG_FAMILIES`
3. Make sure the first tuple element of `sort_key` is the variant
   string (if any), so the prefix-lock fires correctly.
4. Re-run `dream check-image-updates -s <svc>` and confirm the row
   moves out of *Unchecked*.

## Workflow when a bump is available

```bash
# 1. Edit BOTH files in lock-step
$EDITOR extensions/services/<svc>/compose.yaml
$EDITOR installers/phases/08-images.sh

# 2. Verify
dream check-image-updates -s <svc>          # should now say "ok"

# 3. Ship
git commit -am "chore(<svc>): bump to <new-tag>"
git push

# 4. Roll out on the server
dream sync --pull --auto-restart
```

The `--auto-restart` flag in `dream sync` will detect any changed
`compose*.yaml`, `Dockerfile*`, `manifest.*` or `.env*` file under
`extensions/services/<sid>/` — even when the byte-length of the pin
happens to be unchanged (caught by
[`fix(sync): trigger restart for mtime-only changes…`](https://github.com/CodeDredd/DreamServer/commit/1dd15162))
— and restart only those services.

## CI integration

The `--strict` flag exits 1 if any bump is available, making this
suitable as a scheduled CI job:

```yaml
# .github/workflows/image-updates.yml
on: { schedule: [{ cron: "0 6 * * 1" }] }   # Monday 06:00 UTC
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: ./dream-server/dream-cli check-image-updates --strict --repo dream-server
```

Pair with `--json` to feed the result into a Slack/Discord notifier.

## Rate-limiting / free-tier behaviour

* **Docker Hub** unauthenticated: 100 pulls / 6h per IP for the
  manifest endpoints.  This tool only hits the *tag listing* endpoint
  which is generous (no observed throttling at default page count).
* **GHCR** anonymous: pull tokens are issued without authentication
  for public repos; the script fetches one per repo per invocation.

If you ever do hit a 429, lower `--max-pages-dockerhub` /
`--max-pages-ghcr`, or restrict to a few services with `-s`.

