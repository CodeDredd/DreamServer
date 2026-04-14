# Dream Server Windows Quickstart

> **Status: Supported today**
>
> Dream Server runs on Windows today through **Docker Desktop with the WSL2 backend**. The Windows installer (`.\install.ps1`) performs preflight checks, installs the stack, and hands off runtime orchestration to the Windows CLI (`dream.ps1`).
>
> See the [Support Matrix](SUPPORT-MATRIX.md) for current platform status.

---

## What Works Today

- Complete install and runtime on Windows 10/11 with Docker Desktop + WSL2
- GPU-aware install flow for NVIDIA and AMD Windows paths
- Service management through `.\dream-server\installers\windows\dream.ps1`
- Diagnostics and support bundles via the Windows CLI

Install from a PowerShell session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
git clone https://github.com/Light-Heart-Labs/DreamServer.git
cd DreamServer
.\install.ps1
```

After install, manage the stack with the Windows CLI:

```powershell
.\dream-server\installers\windows\dream.ps1 status
.\dream-server\installers\windows\dream.ps1 start
.\dream-server\installers\windows\dream.ps1 stop
.\dream-server\installers\windows\dream.ps1 restart
.\dream-server\installers\windows\dream.ps1 logs open-webui 100
.\dream-server\installers\windows\dream.ps1 update
.\dream-server\installers\windows\dream.ps1 report
```

Open the dashboard at **http://localhost:3000** after services are up.

---

## Requirements

- Windows 10 version 2004+ or Windows 11
- Docker Desktop with **WSL2 backend enabled**
- A WSL2 distro installed and working
- NVIDIA GPU or AMD Strix Halo hardware for accelerated local inference
- Enough RAM / VRAM for the selected model tier

CPU-only and cloud-assisted workflows are possible, but the best local experience still depends on hardware fit.

---

## What The Installer Does

`.\install.ps1` performs the Windows-specific setup flow:

1. Checks WSL2, Docker Desktop, and GPU readiness
2. Selects an install tier based on detected hardware
3. Generates the Dream Server environment and credentials
4. Starts the required services
5. Leaves you with `dream.ps1` for day-to-day management

The Windows path is not a "diagnostics-only" stub anymore. The preflight checks are part of the real installer flow.

---

## Common Commands

```powershell
# Overall health, service state, GPU path, and agent status
.\dream-server\installers\windows\dream.ps1 status

# Restart one service
.\dream-server\installers\windows\dream.ps1 restart open-webui

# Tail logs
.\dream-server\installers\windows\dream.ps1 logs llama-server 50

# Open or inspect config
.\dream-server\installers\windows\dream.ps1 config show
.\dream-server\installers\windows\dream.ps1 config edit

# Host agent controls
.\dream-server\installers\windows\dream.ps1 agent status
.\dream-server\installers\windows\dream.ps1 agent restart
```

Run `.\dream-server\installers\windows\dream.ps1 help` for the full command list.

---

## Known Constraints

- Windows runtime depends on Docker Desktop + WSL2 rather than a pure native service stack.
- Hardware validation is broader on Linux than on Windows today.
- Intel Arc remains experimental overall; see the support docs before planning around it.

These are support-scope constraints, not "coming soon" blockers.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Docker Desktop is not running | Start Docker Desktop and wait for it to finish booting |
| WSL2 is missing | Run `wsl --install`, reboot if prompted, then retry |
| GPU is not visible | Update drivers, restart Docker Desktop, rerun `dream.ps1 status` |
| A service is unhealthy | Inspect logs with `dream.ps1 logs <service>` and generate a bundle with `dream.ps1 report` |

More references:
- [WINDOWS-INSTALL-WALKTHROUGH.md](WINDOWS-INSTALL-WALKTHROUGH.md)
- [WSL2-GPU-TROUBLESHOOTING.md](WSL2-GPU-TROUBLESHOOTING.md)
- [DOCKER-DESKTOP-OPTIMIZATION.md](DOCKER-DESKTOP-OPTIMIZATION.md)

---

*Last updated: 2026-04-14*
