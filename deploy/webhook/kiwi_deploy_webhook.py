#!/usr/bin/env python3
"""Minimal authenticated webhook for GHCR-backed EC2 deploys."""

from __future__ import annotations

import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer


WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "127.0.0.1")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8787"))
DEPLOY_TOKEN = os.getenv("DEPLOY_WEBHOOK_SECRET", "")
APP_DIR = os.getenv("DEPLOY_APP_DIR", "/opt/kiwi")
COMPOSE_FILE = os.getenv("DEPLOY_COMPOSE_FILE", "docker-compose.ec2.yml")
BACKEND_SERVICE = os.getenv("DEPLOY_BACKEND_SERVICE", "backend")
ENV_FILE = os.getenv("DEPLOY_ENV_FILE", os.path.join(APP_DIR, "webhook.env"))


def _compose_cmd(subcommand: str) -> str:
    return "docker compose --env-file {env} -f {compose} {subcommand}".format(
        env=ENV_FILE,
        compose=COMPOSE_FILE,
        subcommand=subcommand,
    )


def _run(cmd: str) -> str:
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
        detail = (result.stderr or result.stdout or "unknown error").strip()
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        ) from RuntimeError(detail[:2000])
    return (result.stdout or "").strip()


def _cleanup_docker_disk() -> None:
    """Remove dangling layers from previous pulls — does not stop running containers."""
    script = os.path.join(APP_DIR, "scripts", "docker-disk-cleanup.sh")
    if os.path.isfile(script):
        _run("bash {0}".format(script))
        return
    # Fallback if script not copied yet
    _run("docker image prune -f")
    _run("docker container prune -f")
    _run("docker builder prune -f --filter until=72h")


def _deploy() -> None:
    # Pull only changed layers; recreate container if image digest changed
    _run(_compose_cmd("pull {0}".format(BACKEND_SERVICE)))
    _run(_compose_cmd("up -d --remove-orphans {0}".format(BACKEND_SERVICE)))
    try:
        _cleanup_docker_disk()
    except subprocess.CalledProcessError as exc:
        # Deploy succeeded; log cleanup failure but do not fail webhook
        print("post-deploy cleanup warning: {0}".format(exc), flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/deploy":
            self.send_response(404)
            self.end_headers()
            return

        if DEPLOY_TOKEN:
            supplied = self.headers.get("X-Deploy-Token", "")
            if supplied != DEPLOY_TOKEN:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"forbidden")
                return

        try:
            _deploy()
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.output or str(exc)).strip()
            print(f"deploy failed: {detail}", flush=True)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"deploy failed: {detail[:2000]}".encode())
            return

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> None:
    server = HTTPServer((WEBHOOK_HOST, WEBHOOK_PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
