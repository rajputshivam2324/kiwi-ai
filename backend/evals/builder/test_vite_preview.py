"""Tests for Vite preview host handling.

The project's vite.config is LLM-authored, so its shape is unpredictable. These
cases are the shapes that previously defeated in-place text patching — most
importantly a config that already declares `server` without `allowedHosts`,
where appending a second `server` key silently lost the allowlist and produced
the production "Blocked request. This host is not allowed" 403.
"""

import json
from pathlib import Path

from app.services.builder.vite_preview import (
    WRAPPER_CONFIG_NAME,
    ensure_vite_allowed_hosts,
)

HOSTS = ["preview.kiwiai.shivamio.in", "localhost", "127.0.0.1"]

CONFIG_SHAPES = {
    "define_config_object": (
        'import { defineConfig } from "vite";\n'
        "export default defineConfig({ plugins: [] });\n"
    ),
    "server_block_without_allowed_hosts": (
        'import { defineConfig } from "vite";\n'
        "export default defineConfig({\n"
        "  server: { port: 5173, strictPort: true },\n"
        "});\n"
    ),
    "multiline_allowed_hosts_array": (
        'import { defineConfig } from "vite";\n'
        "export default defineConfig({\n"
        "  server: {\n"
        "    allowedHosts: [\n"
        '      "localhost",\n'
        "    ],\n"
        "  },\n"
        "});\n"
    ),
    "arrow_function_config": (
        'import { defineConfig } from "vite";\n'
        "export default defineConfig(({ mode }) => ({\n"
        "  server: { host: true },\n"
        "}));\n"
    ),
    "bare_object_export": "export default {\n  server: { port: 5173 },\n};\n",
}


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_wrapper_generated_for_every_config_shape(tmp_path: Path) -> None:
    for label, body in CONFIG_SHAPES.items():
        project = tmp_path / label
        project.mkdir()
        user_cfg = _write(project, "vite.config.ts", body)
        original = user_cfg.read_text(encoding="utf-8")

        config_name = ensure_vite_allowed_hosts(project, HOSTS)

        assert config_name == WRAPPER_CONFIG_NAME, label
        wrapper = project / WRAPPER_CONFIG_NAME
        assert wrapper.exists(), label

        text = wrapper.read_text(encoding="utf-8")
        # Allowlist is present exactly once, as a single JSON array literal.
        assert f"const allowedHosts = {json.dumps(HOSTS)};" in text, label
        # The wrapper composes the project's config rather than replacing it.
        assert 'import userConfigExport from "./vite.config.ts";' in text, label
        # ...and never mutates it, so no chance of a duplicate `server` key.
        assert user_cfg.read_text(encoding="utf-8") == original, label


def test_wrapper_targets_the_config_vite_would_have_loaded(tmp_path: Path) -> None:
    # Vite resolves vite.config.js before vite.config.ts.
    _write(tmp_path, "vite.config.ts", "export default {};\n")
    _write(tmp_path, "vite.config.js", "export default {};\n")

    ensure_vite_allowed_hosts(tmp_path, True)

    text = (tmp_path / WRAPPER_CONFIG_NAME).read_text(encoding="utf-8")
    assert 'from "./vite.config.js"' in text
    assert "vite.config.ts" not in text


def test_creates_config_when_missing(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"todo"}', encoding="utf-8")

    config_name = ensure_vite_allowed_hosts(tmp_path, True)

    assert config_name == "vite.config.ts"
    cfg = tmp_path / "vite.config.ts"
    assert cfg.exists()
    assert "allowedHosts: true" in cfg.read_text(encoding="utf-8")
    # No wrapper needed when we authored the config ourselves.
    assert not (tmp_path / WRAPPER_CONFIG_NAME).exists()


def test_empty_allowlist_falls_back_to_permissive(tmp_path: Path) -> None:
    _write(tmp_path, "vite.config.ts", "export default {};\n")

    ensure_vite_allowed_hosts(tmp_path, [])

    text = (tmp_path / WRAPPER_CONFIG_NAME).read_text(encoding="utf-8")
    assert "const allowedHosts = true;" in text
