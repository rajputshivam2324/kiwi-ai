#!/usr/bin/env python3
"""Minimal authenticated webhook for GHCR-backed EC2 deploys.

Every failure response carries the failing step plus a hint, because the only
thing the GitHub Actions log can show is the HTTP status and this body.

Endpoints:
  GET  /health   preflight status — safe to call anytime, changes nothing
  POST /deploy   pull the published image and recreate the backend container
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "127.0.0.1")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8787"))
DEPLOY_TOKEN = os.getenv("DEPLOY_WEBHOOK_SECRET", "")
APP_DIR = os.getenv("DEPLOY_APP_DIR", "/opt/kiwi")
COMPOSE_FILE = os.getenv("DEPLOY_COMPOSE_FILE", "docker-compose.ec2.yml")
BACKEND_SERVICE = os.getenv("DEPLOY_BACKEND_SERVICE", "backend")
ENV_FILE = os.getenv("DEPLOY_ENV_FILE", os.path.join(APP_DIR, "webhook.env"))

# `docker compose pull` needs this much headroom to unpack a new image layer set.
MIN_FREE_BYTES = int(os.getenv("DEPLOY_MIN_FREE_BYTES", str(2 * 1024**3)))

GHCR_REGISTRY = "ghcr.io"

SYNC_SCRIPT = os.path.join(APP_DIR, "scripts", "sync-deploy-assets.sh")
# Seconds to wait after answering before exiting for a self-restart. systemd's
# Restart=always brings us straight back up on the new code.
SELF_RESTART_DELAY = 2.0


class DeployError(RuntimeError):
    """Carries which step failed and what to do about it."""

    def __init__(self, step: str, detail: str, hint: str = "") -> None:
        self.step = step
        self.detail = (detail or "unknown error").strip()[:2000]
        self.hint = hint
        super().__init__(f"[{step}] {self.detail}")

    def payload(self) -> dict[str, str]:
        body = {"ok": False, "step": self.step, "error": self.detail}
        if self.hint:
            body["hint"] = self.hint
        return body


def _read_env_file(path: str) -> dict[str, str]:
    """Parse KEY=VALUE lines.

    Read from disk rather than trusting os.environ: systemd loads webhook.env
    at service start, so an edited file is invisible to this process until a
    restart. Validating against the file is what the deploy actually uses.
    """
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("'\"")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    return values


def _deploy_env() -> dict[str, str]:
    merged = dict(os.environ)
    merged.update(_read_env_file(ENV_FILE))
    return merged


def _compose_cmd(subcommand: str) -> str:
    return "docker compose --env-file {env} -f {compose} {subcommand}".format(
        env=ENV_FILE,
        compose=COMPOSE_FILE,
        subcommand=subcommand,
    )


def _run(cmd: str, step: str, hint: str = "") -> str:
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=APP_DIR,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        detail = result.stderr or result.stdout or "unknown error"
        raise DeployError(step, detail, hint)
    return (result.stdout or "").strip()


def _preflight() -> dict[str, object]:
    """Validate the things that actually break deploys, with actionable errors."""
    env = _deploy_env()
    checks: dict[str, object] = {}

    if not os.path.isdir(APP_DIR):
        raise DeployError(
            "preflight:app_dir",
            f"{APP_DIR} does not exist",
            "Create it and copy docker-compose.ec2.yml + backend.env there.",
        )
    checks["app_dir"] = APP_DIR

    compose_path = os.path.join(APP_DIR, COMPOSE_FILE)
    if not os.path.isfile(compose_path):
        raise DeployError(
            "preflight:compose_file",
            f"{compose_path} not found",
            "Copy deploy/docker-compose.ec2.yml to the app directory.",
        )
    checks["compose_file"] = compose_path

    if not os.path.isfile(ENV_FILE):
        raise DeployError(
            "preflight:env_file",
            f"{ENV_FILE} not found",
            "Copy deploy/webhook.env.example to this path and fill it in.",
        )
    checks["env_file"] = ENV_FILE

    backend_image = env.get("BACKEND_IMAGE", "").strip()
    if not backend_image:
        raise DeployError(
            "preflight:backend_image",
            f"BACKEND_IMAGE is not set in {ENV_FILE}",
            "docker-compose.ec2.yml requires it. Set e.g. "
            "BACKEND_IMAGE=ghcr.io/<owner>/kiwi-ai-backend:latest",
        )
    checks["backend_image"] = backend_image

    if shutil.which("docker") is None:
        raise DeployError(
            "preflight:docker",
            "docker not found on PATH",
            "Install Docker and ensure the webhook service user can run it.",
        )

    usage = shutil.disk_usage(APP_DIR)
    checks["disk_free_bytes"] = usage.free
    checks["disk_free_human"] = f"{usage.free / 1024**3:.1f}G"
    checks["disk_low"] = usage.free < MIN_FREE_BYTES

    checks["ghcr_login_configured"] = bool(
        env.get("GHCR_TOKEN") and env.get("GHCR_USERNAME")
    )
    return checks


def _ghcr_login() -> bool:
    """Log in to GHCR when credentials are configured.

    Images published by GitHub Actions are private by default, so an
    unauthenticated `docker compose pull` fails with "denied" / "unauthorized".
    """
    env = _deploy_env()
    username = env.get("GHCR_USERNAME", "").strip()
    token = env.get("GHCR_TOKEN", "").strip()
    if not username or not token:
        return False

    result = subprocess.run(
        ["docker", "login", GHCR_REGISTRY, "-u", username, "--password-stdin"],
        input=token,
        cwd=APP_DIR,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Never echo the token back.
        detail = (result.stderr or result.stdout or "docker login failed").strip()
        raise DeployError(
            "ghcr_login",
            detail,
            "Check GHCR_USERNAME and GHCR_TOKEN in webhook.env. The token needs "
            "the read:packages scope.",
        )
    return True


def _sync_host_assets() -> dict[str, str]:
    """Pull deploy/ from git onto the host before deploying the image.

    Best-effort: the app deploy matters more than the infra refresh, so a sync
    failure is reported but never raised.
    """
    if not os.path.isfile(SYNC_SCRIPT):
        return {"status": "missing"}

    result = subprocess.run(
        ["bash", SYNC_SCRIPT],
        cwd=APP_DIR,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=300,
    )
    output = f"{result.stdout}\n{result.stderr}"
    for line in output.splitlines():
        if line.strip():
            print(f"sync: {line.rstrip()}", flush=True)

    markers = {}
    for line in output.splitlines():
        line = line.strip()
        if "=" in line and line.split("=", 1)[0].isupper():
            key, _, value = line.partition("=")
            markers[key] = value

    return {
        "status": markers.get("SYNC_STATUS", "unknown"),
        "webhook_updated": markers.get("WEBHOOK_UPDATED", "0"),
        "compose_updated": markers.get("COMPOSE_UPDATED", "0"),
        "nginx_updated": markers.get("NGINX_UPDATED", "0"),
    }


def _schedule_self_restart() -> None:
    """Exit shortly after responding so systemd restarts us on the new code.

    Replacing our own source mid-request is not possible, so the running
    process keeps serving the old code until it exits. Requires
    Restart=always in the unit, which kiwi-deploy-webhook.service sets.
    """

    def _exit_later() -> None:
        time.sleep(SELF_RESTART_DELAY)
        print("webhook source changed — exiting for systemd restart", flush=True)
        os._exit(0)

    threading.Thread(target=_exit_later, daemon=True).start()


def _cleanup_docker_disk() -> None:
    """Remove dangling layers from previous pulls — does not stop containers."""
    script = os.path.join(APP_DIR, "scripts", "docker-disk-cleanup.sh")
    if os.path.isfile(script):
        _run("bash {0}".format(script), "cleanup")
        return
    _run("docker image prune -f", "cleanup")
    _run("docker container prune -f", "cleanup")
    _run("docker builder prune -f --filter until=72h", "cleanup")


def _deploy() -> dict[str, object]:
    checks = _preflight()

    # Free space before pulling rather than after failing on a full disk.
    if checks.get("disk_low"):
        try:
            _cleanup_docker_disk()
            usage = shutil.disk_usage(APP_DIR)
            checks["disk_free_after_cleanup"] = f"{usage.free / 1024**3:.1f}G"
            if usage.free < MIN_FREE_BYTES:
                raise DeployError(
                    "preflight:disk",
                    f"only {usage.free / 1024**3:.1f}G free after cleanup",
                    "Free space on the instance or grow the EBS volume.",
                )
        except DeployError:
            raise
        except Exception as exc:  # cleanup is best-effort
            print(f"pre-deploy cleanup warning: {exc}", flush=True)

    # Refresh host-side deploy assets first, so the compose file used by the
    # pull below is the one from this commit.
    sync = _sync_host_assets()
    checks["sync"] = sync

    checks["ghcr_login"] = _ghcr_login()

    pull_hint = (
        "If this says 'denied' or 'unauthorized', the GHCR package is private. "
        "Either make it public in GitHub > Packages > Package settings, or set "
        "GHCR_USERNAME and GHCR_TOKEN (read:packages) in webhook.env."
    )
    _run(_compose_cmd(f"pull {BACKEND_SERVICE}"), "compose_pull", pull_hint)
    _run(_compose_cmd(f"up -d --remove-orphans {BACKEND_SERVICE}"), "compose_up")

    try:
        _cleanup_docker_disk()
    except DeployError as exc:
        # Deploy already succeeded; a cleanup failure must not fail the webhook.
        print(f"post-deploy cleanup warning: {exc}", flush=True)

    return checks


class Handler(BaseHTTPRequestHandler):
    server_version = "KiwiDeployWebhook/1.1"

    def _respond(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not DEPLOY_TOKEN:
            return True
        return self.headers.get("X-Deploy-Token", "") == DEPLOY_TOKEN

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._respond(404, {"ok": False, "error": "not found"})
            return
        # Reachable through the public /deploy-health route, and the payload
        # names image, paths and disk stats — so require the token here too.
        if not self._authorized():
            self._respond(403, {"ok": False, "error": "forbidden"})
            return
        try:
            self._respond(200, {"ok": True, "checks": _preflight()})
        except DeployError as exc:
            self._respond(503, exc.payload())

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/deploy":
            self._respond(404, {"ok": False, "error": "not found"})
            return

        if not self._authorized():
            self._respond(403, {"ok": False, "error": "forbidden"})
            return

        try:
            checks = _deploy()
        except DeployError as exc:
            print(f"deploy failed: {exc}", flush=True)
            self._respond(500, exc.payload())
            return
        except Exception as exc:  # noqa: BLE001 — must always answer the caller
            print(f"deploy failed (unexpected): {exc!r}", flush=True)
            self._respond(500, {"ok": False, "step": "unknown", "error": str(exc)})
            return

        sync = checks.get("sync") or {}
        restarting = sync.get("webhook_updated") == "1"

        print(f"deploy ok: {checks.get('backend_image')}", flush=True)
        self._respond(
            200,
            {
                "ok": True,
                "deployed": checks.get("backend_image"),
                "sync": sync,
                "webhook_restarting": restarting,
            },
        )

        # Answer first, then swap ourselves out.
        if restarting:
            _schedule_self_restart()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> None:
    server = HTTPServer((WEBHOOK_HOST, WEBHOOK_PORT), Handler)
    print(
        f"deploy webhook listening on {WEBHOOK_HOST}:{WEBHOOK_PORT} "
        f"(app_dir={APP_DIR}, env_file={ENV_FILE})",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
