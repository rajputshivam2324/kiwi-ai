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


def _run(cmd: str) -> None:
    subprocess.run(
        cmd,
        shell=True,
        cwd=APP_DIR,
        check=True,
        env=os.environ.copy(),
    )


def _deploy() -> None:
    _run("docker compose -f {0} pull {1}".format(COMPOSE_FILE, BACKEND_SERVICE))
    _run("docker compose -f {0} up -d {1}".format(COMPOSE_FILE, BACKEND_SERVICE))


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
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"deploy failed: {exc}".encode())
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
