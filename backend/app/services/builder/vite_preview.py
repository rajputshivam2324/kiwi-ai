"""Ensure generated Vite apps accept reverse-proxied preview hostnames."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_NAMES = ("vite.config.ts", "vite.config.js", "vite.config.mjs")


def _allowed_hosts_literal(allowed_hosts: list[str] | bool) -> str:
    if allowed_hosts is True:
        return "true"
    return json.dumps(allowed_hosts)


def _inject_server_block(text: str, allowed_literal: str) -> str:
    snippet = f"""  server: {{
    host: true,
    allowedHosts: {allowed_literal},
  }},
"""
    if "defineConfig({" in text:
        return text.replace("defineConfig({", f"defineConfig({{\n{snippet}", 1)
    if "export default {" in text:
        return text.replace("export default {", f"export default {{\n{snippet}", 1)
    return text


def _replace_allowed_hosts(text: str, allowed_literal: str) -> str:
    if re.search(r"allowedHosts\s*:\s*true\b", text):
        if allowed_literal == "true":
            return text
        return re.sub(
            r"allowedHosts\s*:\s*true",
            f"allowedHosts: {allowed_literal}",
            text,
            count=1,
        )
    return re.sub(
        r"allowedHosts\s*:\s*\[[^\]]*\]",
        f"allowedHosts: {allowed_literal}",
        text,
        count=1,
    )


def ensure_vite_allowed_hosts(
    project_path: Path,
    allowed_hosts: list[str] | bool,
) -> bool:
    """
    Patch vite.config so Vite accepts Host header from Nginx (e.g. preview.kiwiai.shivamio.in).
    Returns True if a config file was updated.
    """
    allowed_literal = _allowed_hosts_literal(allowed_hosts)

    for name in _CONFIG_NAMES:
        path = project_path / name
        if not path.exists():
            continue

        text = path.read_text(encoding="utf-8")
        original = text

        if "allowedHosts" in text:
            text = _replace_allowed_hosts(text, allowed_literal)
        else:
            text = _inject_server_block(text, allowed_literal)

        if text != original:
            path.write_text(text, encoding="utf-8")
            logger.info("Patched %s allowedHosts for preview proxy", path.name)
            return True

        return False

    logger.warning("No vite.config found under %s — preview host check may fail", project_path)
    return False
