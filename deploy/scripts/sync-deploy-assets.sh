#!/usr/bin/env bash
# Sync host-side deploy assets from git.
#
# The Docker image only contains backend/. Everything under deploy/ runs on the
# host (webhook service, compose file, nginx), so without this a push updates
# the app but never the infrastructure around it.
#
# The deploy webhook runs this before pulling the image, which makes a push to
# main update both. Disabled unless DEPLOY_REPO_URL is set.
#
# Contract: prints KEY=VALUE markers on stdout for the webhook to read.
#   SYNC_STATUS=disabled|ok|failed
#   WEBHOOK_UPDATED=1     the webhook's own source changed; it must restart
#   COMPOSE_UPDATED=1
#   NGINX_UPDATED=1
# Exit code is always 0: a sync problem must not block the app deploy.

set -uo pipefail

APP_DIR="${DEPLOY_APP_DIR:-/opt/kiwi}"
SRC_DIR="${DEPLOY_SRC_DIR:-${APP_DIR}/src}"
REPO_URL="${DEPLOY_REPO_URL:-}"
BRANCH="${DEPLOY_REPO_BRANCH:-main}"
# nginx sync is opt-in: certbot rewrites the installed configs, so overwriting
# them can break TLS. Enable once you are happy the repo copies are current.
SYNC_NGINX="${DEPLOY_SYNC_NGINX:-0}"
NGINX_SITES="${DEPLOY_NGINX_SITES_DIR:-/etc/nginx/sites-available}"

webhook_updated=0
compose_updated=0
nginx_updated=0

log() { printf '[sync] %s\n' "$*"; }

# Never print REPO_URL: it may embed a token for a private repo.
redacted_url() { printf '%s' "${REPO_URL}" | sed -E 's#//[^@/]+@#//***@#'; }

finish() {
  [ "${webhook_updated}" = "1" ] && echo "WEBHOOK_UPDATED=1"
  [ "${compose_updated}" = "1" ] && echo "COMPOSE_UPDATED=1"
  [ "${nginx_updated}" = "1" ] && echo "NGINX_UPDATED=1"
  echo "SYNC_STATUS=$1"
  exit 0
}

if [ -z "${REPO_URL}" ]; then
  log "DEPLOY_REPO_URL not set — skipping host asset sync"
  finish disabled
fi

if ! command -v git >/dev/null 2>&1; then
  log "git not installed — cannot sync host assets"
  finish failed
fi

# --- fetch the repo -----------------------------------------------------------
log "syncing $(redacted_url) @ ${BRANCH}"
if [ -d "${SRC_DIR}/.git" ]; then
  git -C "${SRC_DIR}" remote set-url origin "${REPO_URL}" >/dev/null 2>&1
  if ! git -C "${SRC_DIR}" fetch --depth 1 origin "${BRANCH}" >/dev/null 2>&1; then
    log "git fetch failed"
    finish failed
  fi
  git -C "${SRC_DIR}" reset --hard "origin/${BRANCH}" >/dev/null 2>&1 || {
    log "git reset failed"
    finish failed
  }
else
  rm -rf "${SRC_DIR}"
  mkdir -p "$(dirname "${SRC_DIR}")"
  if ! git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${SRC_DIR}" >/dev/null 2>&1; then
    log "git clone failed — check DEPLOY_REPO_URL and repo visibility"
    finish failed
  fi
fi

SRC_DEPLOY="${SRC_DIR}/deploy"
if [ ! -d "${SRC_DEPLOY}" ]; then
  log "no deploy/ directory in the checkout"
  finish failed
fi

log "at commit $(git -C "${SRC_DIR}" rev-parse --short HEAD)"

# --- copy helpers -------------------------------------------------------------
# Returns 0 (true) when the destination changed.
copy_file() {
  local src="$1" dst="$2" mode="${3:-0644}"
  [ -f "${src}" ] || return 1
  if [ -f "${dst}" ] && cmp -s "${src}" "${dst}"; then
    return 1
  fi
  mkdir -p "$(dirname "${dst}")"
  install -m "${mode}" "${src}" "${dst}" || return 1
  log "updated ${dst}"
  return 0
}

copy_tree() {
  local src="$1" dst="$2" changed=1
  [ -d "${src}" ] || return 1
  local rel
  while IFS= read -r -d '' rel; do
    local mode=0644
    case "${rel}" in *.sh) mode=0755 ;; esac
    if copy_file "${src}/${rel}" "${dst}/${rel}" "${mode}"; then
      changed=0
    fi
  done < <(cd "${src}" && find . -type f -printf '%P\0')
  return "${changed}"
}

# --- /opt/kiwi assets ---------------------------------------------------------
copy_file "${SRC_DEPLOY}/docker-compose.ec2.yml" "${APP_DIR}/docker-compose.ec2.yml" \
  && compose_updated=1
copy_file "${SRC_DEPLOY}/prometheus.yml" "${APP_DIR}/prometheus.yml" || true
copy_tree "${SRC_DEPLOY}/grafana-provisioning" "${APP_DIR}/grafana-provisioning" || true
copy_tree "${SRC_DEPLOY}/scripts" "${APP_DIR}/scripts" || true

# The webhook's own source. It cannot swap its code mid-request, so we only
# flag it here and let the webhook restart itself after responding.
copy_tree "${SRC_DEPLOY}/webhook" "${APP_DIR}/webhook" && webhook_updated=1

# --- systemd unit -------------------------------------------------------------
UNIT_DST=/etc/systemd/system/kiwi-deploy-webhook.service
UNIT_SRC="${SRC_DEPLOY}/systemd/kiwi-deploy-webhook.service"
if [ -f "${UNIT_SRC}" ] && ! cmp -s "${UNIT_SRC}" "${UNIT_DST}"; then
  if install -m 0644 "${UNIT_SRC}" "${UNIT_DST}" 2>/dev/null; then
    if systemctl daemon-reload >/dev/null 2>&1; then
      log "systemd unit changed — daemon-reload done"
      webhook_updated=1
    else
      log "systemd unit changed but daemon-reload failed"
    fi
  else
    log "cannot write ${UNIT_DST} (needs root) — unit left unchanged"
  fi
fi

# --- nginx (opt-in, with test + rollback) -------------------------------------
if [ "${SYNC_NGINX}" = "1" ] && [ -d "${SRC_DEPLOY}/nginx" ]; then
  backup="$(mktemp -d)"
  staged=0
  for conf in "${SRC_DEPLOY}"/nginx/*.conf; do
    [ -f "${conf}" ] || continue
    # api.conf -> api.kiwiai.shivamio.in, matching EC2_DEPLOYMENT.md
    base="$(basename "${conf}" .conf)"
    target=""
    for candidate in \
      "${NGINX_SITES}/${base}.kiwiai.shivamio.in" \
      "${NGINX_SITES}/${base}.conf"; do
      if [ -f "${candidate}" ]; then
        target="${candidate}"
        break
      fi
    done
    # Only refresh sites that are already installed. Creating new ones would
    # need a sites-enabled symlink and a certificate, so that stays manual.
    if [ -z "${target}" ]; then
      log "no installed site matches ${base}.conf — skipping"
      continue
    fi
    cp "${target}" "${backup}/$(basename "${target}")"
    if copy_file "${conf}" "${target}"; then
      staged=1
    fi
  done

  if [ "${staged}" = "1" ]; then
    if nginx -t >/dev/null 2>&1; then
      if systemctl reload nginx >/dev/null 2>&1; then
        log "nginx configs updated and reloaded"
        nginx_updated=1
      else
        log "nginx -t passed but reload failed"
      fi
    else
      # Rolling back matters more than the update: a bad config here takes the
      # API and preview domains offline.
      log "nginx -t FAILED — rolling back nginx configs"
      for saved in "${backup}"/*; do
        [ -f "${saved}" ] && cp "${saved}" "${NGINX_SITES}/$(basename "${saved}")"
      done
      nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1
    fi
  fi
  rm -rf "${backup}"
elif [ -d "${SRC_DEPLOY}/nginx" ]; then
  log "nginx sync disabled (set DEPLOY_SYNC_NGINX=1 to enable)"
fi

finish ok
