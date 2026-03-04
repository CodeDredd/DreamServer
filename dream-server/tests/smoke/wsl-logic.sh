#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "[smoke] WSL dispatch logic"
grep -q "linux|wsl" installers/dispatch.sh
grep -q "WSL2 (Windows)" docs/SUPPORT-MATRIX.md
grep -q "Windows native installer UX" docs/SUPPORT-MATRIX.md

echo "[smoke] PASS wsl-logic"
