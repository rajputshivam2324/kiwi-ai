#!/usr/bin/env bash
# One-time switch to self-syncing deploys.
#
# After this, a push to main updates the backend image AND the host assets under
# /opt/kiwi, with no SSH. Safe to re-run.
#
# Usage (on EC2):
#   sudo DEPLOY_REPO_URL=https://github.com/OWNER/REPO.git \
#        bash deploy/scripts/bootstrap-ec2.sh
#
# Reads DEPLOY_REPO_URL from /opt/kiwi/webhook.env if not passed.

set -euo pipefail

APP_DIR="${DEPLOY_APP_DIR:-/opt/kiwi}"
ENV_FILE="${DEPLOY_ENV_FILE:-${APP_DIR}/webhook.env}"
SERVICE=kiwi-deploy-webhook

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo — this writes to ${APP_DIR} and /etc/systemd/system." >&2
  exit 1
fi

# Locate the repo checkout this script was invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DEPLOY="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [ ! -f "${REPO_DEPLOY}/docker-compose.ec2.yml" ]; then
  echo "Run this from a checkout of the repo (deploy/scripts/bootstrap-ec2.sh)." >&2
  exit 1
fi

command -v git >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq git; }

mkdir -p "${APP_DIR}/webhook" "${APP_DIR}/scripts"

echo "==> Installing host assets into ${APP_DIR}"
install -m 0644 "${REPO_DEPLOY}/docker-compose.ec2.yml" "${APP_DIR}/docker-compose.ec2.yml"
install -m 0644 "${REPO_DEPLOY}/prometheus.yml" "${APP_DIR}/prometheus.yml"
install -m 0644 "${REPO_DEPLOY}/webhook/kiwi_deploy_webhook.py" "${APP_DIR}/webhook/"
for s in "${REPO_DEPLOY}"/scripts/*.sh; do
  install -m 0755 "${s}" "${APP_DIR}/scripts/"
done
mkdir -p "${APP_DIR}/grafana-provisioning"
cp -r "${REPO_DEPLOY}/grafana-provisioning/." "${APP_DIR}/grafana-provisioning/"

echo "==> Installing systemd unit"
install -m 0644 "${REPO_DEPLOY}/systemd/${SERVICE}.service" \
  "/etc/systemd/system/${SERVICE}.service"

if [ ! -f "${ENV_FILE}" ]; then
  install -m 0600 "${REPO_DEPLOY}/webhook.env.example" "${ENV_FILE}"
  echo "!! Created ${ENV_FILE} from the example — fill it in, then re-run." >&2
  exit 1
fi
chmod 0600 "${ENV_FILE}"

# --- make sure the sync can find the repo ------------------------------------
repo_url="${DEPLOY_REPO_URL:-$(grep -E '^DEPLOY_REPO_URL=' "${ENV_FILE}" | cut -d= -f2- || true)}"
if [ -z "${repo_url}" ]; then
  echo "!! DEPLOY_REPO_URL is not set in ${ENV_FILE}." >&2
  echo "   Without it, pushes will update the image but not ${APP_DIR}." >&2
  exit 1
fi
if ! grep -qE '^DEPLOY_REPO_URL=' "${ENV_FILE}"; then
  printf '\n# Added by bootstrap-ec2.sh\nDEPLOY_REPO_URL=%s\n' "${repo_url}" >> "${ENV_FILE}"
  echo "==> Recorded DEPLOY_REPO_URL in ${ENV_FILE}"
fi

echo "==> Restarting ${SERVICE}"
systemctl daemon-reload
systemctl enable --now "${SERVICE}"
systemctl restart "${SERVICE}"
sleep 2
systemctl is-active --quiet "${SERVICE}" || {
  echo "!! ${SERVICE} is not running:" >&2
  journalctl -u "${SERVICE}" -n 30 --no-pager >&2
  exit 1
}

# --- verify -------------------------------------------------------------------
secret="$(grep -E '^DEPLOY_WEBHOOK_SECRET=' "${ENV_FILE}" | cut -d= -f2- || true)"
echo "==> Preflight"
if curl -fsS -H "X-Deploy-Token: ${secret}" http://127.0.0.1:8787/health; then
  echo
  echo "Bootstrap complete. Pushes to main now deploy the app and sync ${APP_DIR}."
else
  echo
  echo "!! Preflight failed — see the JSON above for the failing step." >&2
  exit 1
fi

if [ -z "${secret}" ]; then
  echo
  echo "WARNING: DEPLOY_WEBHOOK_SECRET is empty, so /deploy accepts ANY caller." >&2
  echo "         Set it (openssl rand -hex 32) and match GitHub's" >&2
  echo "         BACKEND_DEPLOY_WEBHOOK_SECRET, then restart the service." >&2
fi
