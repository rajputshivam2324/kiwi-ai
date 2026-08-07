#!/usr/bin/env bash
# Safe Docker disk cleanup for EC2 — removes unused layers, keeps running containers.
set -euo pipefail

echo "=== Disk before ==="
df -h / | tail -1
docker system df 2>/dev/null || true

echo "=== Prune dangling images (old :latest after redeploy) ==="
docker image prune -f

echo "=== Prune stopped containers ==="
docker container prune -f

echo "=== Prune build cache older than 72h ==="
docker builder prune -f --filter until=72h 2>/dev/null || docker builder prune -f 2>/dev/null || true

# Remove untagged backend images still referenced only by old layers
BACKEND_IMAGE="${BACKEND_IMAGE:-ghcr.io/rajputshivam2324/kiwi-ai-backend:latest}"
echo "=== Current backend image: ${BACKEND_IMAGE} ==="

echo "=== Disk after ==="
df -h / | tail -1
docker system df 2>/dev/null || true

echo "Done."
