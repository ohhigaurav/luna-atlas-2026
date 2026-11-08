#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 VM for Luna Atlas. Run on the VM: bash vm_setup.sh
# Installs Docker (with the compose plugin), adds swap, clones the repo and makes the data folders.
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

# 4 GB swap: a cushion for the DEM and horizon work on a small VM (harmless if RAM is ample).
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

if [ ! -d "$HOME/luna-atlas/.git" ]; then
  git clone https://github.com/ohhigaurav/luna-atlas-2026.git "$HOME/luna-atlas"
fi
mkdir -p "$HOME/luna-atlas/data/"{kernels,dems/assets,cache,runs,scans,ensembles} "$HOME/luna-atlas/frontend/app/dist"
[ -f "$HOME/luna-atlas/deploy/.env" ] || cp "$HOME/luna-atlas/deploy/env.example" "$HOME/luna-atlas/deploy/.env"

echo
echo "Done. Next (an internal document (not published)):"
echo "  1. log out and back in (so 'docker' works without sudo)"
echo "  2. edit ~/luna-atlas/deploy/.env"
echo "  3. copy kernels, DEMs and the built app from your laptop with rsync (step 4 of the guide)"
