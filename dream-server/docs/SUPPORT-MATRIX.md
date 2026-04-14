# Dream Server Support Matrix

Last updated: 2026-04-14

## What Works Today

**Linux, Windows, and macOS are supported today. Intel Arc remains experimental.**

| Platform | Status | What you get today |
|----------|--------|-------------------|
| **Linux + AMD Strix Halo (ROCm)** | **Fully supported** | Complete install and runtime. Primary development platform. |
| **Linux + NVIDIA (CUDA)** | **Supported** | Complete install and runtime. Broader distro and hardware validation is still expanding. |
| **Windows (Docker Desktop + WSL2)** | **Supported** | Complete install and runtime via `.\install.ps1`, with ongoing runtime management through `dream.ps1`. |
| **macOS (Apple Silicon)** | **Supported** | Complete install and runtime via `./install.sh`, with native Metal inference plus Docker-managed services. |
| **Linux + Intel Arc (SYCL)** | **Experimental** | Installer auto-detects Arc, assigns `ARC`/`ARC_LITE`, and selects the Arc compose overlay. Runtime works on validated Linux Arc hardware, but coverage is still limited. |

## Support Tiers

- `Tier A` — fully supported and actively tested in this repo
- `Tier B` — supported end to end, with validation breadth still expanding
- `Tier C` — experimental or early support paths

## Platform Matrix

| Platform | GPU Path | Installer Tier | Notes |
|---|---|---|---|
| Linux (Ubuntu/Debian family) | NVIDIA (llama-server/CUDA) | Tier B | Installer path exists in `install-core.sh`; broader distro matrix continues to expand |
| Linux (Strix Halo / AMD unified memory) | AMD (llama-server/ROCm) | Tier A | Primary path via `docker-compose.base.yml` + `docker-compose.amd.yml` |
| Linux (Intel Arc A770/A750/B580 class) | Intel SYCL (llama-server/oneAPI) | Tier C | `docker-compose.arc.yml`; see [INTEL-ARC-GUIDE.md](INTEL-ARC-GUIDE.md) for current limitations |
| Windows (Docker Desktop + WSL2) | NVIDIA / AMD via Docker Desktop and WSL2 | Tier B | Standalone installer plus `dream.ps1` for status, restart, logs, updates, and reporting |
| macOS (Apple Silicon) | Metal (native llama-server) | Tier B | Standalone installer with chip detection, native Metal inference, and Docker-managed companion services |

## GPU Tier Map

| Installer Tier | Hardware | Model | VRAM | Backend |
|---|---|---|---|---|
| `NV_ULTRA` | NVIDIA 90 GB+ | Qwen3-Coder-Next | ≥ 90 GB | CUDA |
| `SH_LARGE` | AMD Strix Halo 90+ | Qwen3-Coder-Next | ≥ 90 GB (unified) | ROCm |
| `SH_COMPACT` | AMD Strix Halo < 90 GB | Qwen3 30B A3B | < 90 GB (unified) | ROCm |
| `4` | NVIDIA 40 GB+ / multi-GPU | Qwen3 30B A3B | ≥ 40 GB | CUDA |
| `3` | NVIDIA 20 GB+ | Qwen3 30B-A3B | ≥ 20 GB | CUDA |
| `ARC` | Intel Arc ≥ 12 GB | Qwen3.5 9B | ≥ 12 GB | SYCL |
| `2` | NVIDIA 12 GB+ | Qwen3.5 9B | ≥ 12 GB | CUDA |
| `ARC_LITE` | Intel Arc < 12 GB | Qwen3.5 4B | 6–11 GB | SYCL |
| `1` | NVIDIA 4 GB+ | Qwen3.5 9B | ≥ 4 GB | CUDA |
| `0` | CPU / < 4 GB GPU | Qwen3.5 2B | any | CPU |
| `CLOUD` | No local GPU | Claude (API) | — | LiteLLM |

## Current Truth

- **Linux, Windows, and macOS are supported.**
- Linux + NVIDIA is supported, with broader validation still in progress.
- Windows installs through `.\install.ps1` and runs through Docker Desktop + WSL2, with `dream.ps1` as the operational CLI.
- macOS installs through `./install.sh`; llama-server runs natively with Metal acceleration while companion services run in Docker.
- **Intel Arc is experimental.** The installer path exists, but validation and feature coverage are still narrower than the main supported platforms.
- Version baselines for triage live in `docs/KNOWN-GOOD-VERSIONS.md`.

## CI / Validation Coverage

Current repo validation already includes:

- Linux AMD smoke coverage
- Linux NVIDIA smoke coverage
- Windows/WSL logic smoke coverage
- macOS dispatch smoke coverage

The work now is breadth and confidence expansion, not "adding the first smoke matrix."

## Roadmap

| Target | Milestone |
|--------|-----------|
| **Now** | Linux AMD + NVIDIA + Windows + macOS supported |
| **Now** | Intel Arc experimental — installer + runtime on validated Linux Arc hardware |
| **Ongoing** | Expand hardware coverage and deepen release confidence for NVIDIA, Windows, and macOS |
| **Planned** | Promote Intel Arc to Tier B after broader A770/B580 validation |
| **Planned** | Arc-accelerated Whisper STT overlay |

## Next Milestones

1. Expand Linux NVIDIA coverage across more distros and GPU classes.
2. Expand macOS testing across M1/M2/M3/M4 variants and memory tiers.
3. Improve Windows validation breadth across more Docker Desktop, WSL2, and GPU combinations.
4. Validate Intel Arc B580 and additional Battlemage-class hardware on the Arc path.
5. Promote Intel Arc from Tier C to Tier B after broader real-hardware validation.

## See also

- [LINUX-PORTABILITY.md](LINUX-PORTABILITY.md) — Linux installer edge cases, `.env` validation, and extension manifests
- [WINDOWS-QUICKSTART.md](WINDOWS-QUICKSTART.md) — Windows install and runtime workflow
