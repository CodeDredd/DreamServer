#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[gate] shell syntax"
mapfile -t sh_files < <(git ls-files '*.sh')
for f in "${sh_files[@]}"; do
  bash -n "$f"
done

echo "[gate] compatibility + claims"
bash scripts/check-compatibility.sh
bash scripts/check-release-claims.sh

echo "[gate] contracts"
bash tests/contracts/test-installer-contracts.sh
bash tests/contracts/test-preflight-fixtures.sh

echo "[gate] smoke"
bash tests/smoke/linux-amd.sh
bash tests/smoke/linux-nvidia.sh
bash tests/smoke/wsl-logic.sh
bash tests/smoke/macos-dispatch.sh

echo "[gate] installer simulation"
bash scripts/simulate-installers.sh
python3 scripts/validate-sim-summary.py artifacts/installer-sim/summary.json

echo "[PASS] release gate"
