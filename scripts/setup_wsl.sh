#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu (WSL on Windows): system Python, Node 22 via nvm, then start the
# app. Safe to run again. After this, start the app with: bash scripts/run_local.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip curl ca-certificates
export NVM_DIR="$HOME/.nvm"
if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
  curl -fsSL -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
fi
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
nvm install 22
nvm alias default 22
cd "$ROOT"
echo
echo "Setup done. Starting Luna Atlas: open http://127.0.0.1:8000 in your Windows browser when it says 'Uvicorn running'."
exec bash scripts/run_local.sh
