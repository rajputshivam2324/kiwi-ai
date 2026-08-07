"""Ensure generated Vite apps accept reverse-proxied preview hostnames."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_NAMES = ("vite.config.ts", "vite.config.js", "vite.config.mjs")

_DEFAULT_VITE_CONFIG = """import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    allowedHosts: true,
  },
});
"""


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
    patterns = (
        ("defineConfig({", f"defineConfig({{\n{snippet}"),
        ("defineConfig(\n  {", f"defineConfig(\n  {{\n{snippet}"),
        ("defineConfig( {", f"defineConfig( {{\n{snippet}"),
        ("export default {", f"export default {{\n{snippet}"),
    )
    for needle, replacement in patterns:
        if needle in text:
            return text.replace(needle, replacement, 1)
    return text


def _replace_allowed_hosts(text: str, allowed_literal: str) -> str:
    if re.search(r"allowedHosts\s*:", text):
        return re.sub(
            r"allowedHosts\s*:\s*[^,\n}]+",
            f"allowedHosts: {allowed_literal}",
            text,
            count=1,
        )
    return text


def _create_default_config(project_path: Path) -> Path:
    path = project_path / "vite.config.ts"
    path.write_text(_DEFAULT_VITE_CONFIG, encoding="utf-8")
    logger.info("Created %s with allowedHosts for preview proxy", path.name)
    return path


def ensure_vite_allowed_hosts(
    project_path: Path,
    allowed_hosts: list[str] | bool,
) -> bool:
    """
    Patch vite.config so Vite accepts Host header from Nginx (e.g. preview.kiwiai.shivamio.in).
    Creates vite.config.ts when missing. Returns True if filesystem changed.
    """
    allowed_literal = _allowed_hosts_literal(allowed_hosts)

    existing = [project_path / name for name in _CONFIG_NAMES if (project_path / name).exists()]
    if not existing:
        _create_default_config(project_path)
        return True

    for path in existing:
        text = path.read_text(encoding="utf-8")
        original = text

        if "allowedHosts" in text:
            text = _replace_allowed_hosts(text, allowed_literal)
        else:
            text = _inject_server_block(text, allowed_literal)

        if text == original:
            text = _inject_server_block(text, allowed_literal)

        if text != original:
            path.write_text(text, encoding="utf-8")
            logger.info("Patched %s allowedHosts for preview proxy", path.name)
            return True

    logger.warning("Could not patch vite config under %s", project_path)
    return False
