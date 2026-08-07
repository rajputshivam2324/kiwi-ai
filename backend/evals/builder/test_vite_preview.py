"""Tests for Vite preview host patching."""

from pathlib import Path

from app.services.builder.vite_preview import ensure_vite_allowed_hosts


def test_inject_allowed_hosts_into_vite_config(tmp_path: Path) -> None:
    cfg = tmp_path / "vite.config.ts"
    cfg.write_text(
        'import { defineConfig } from "vite"\n'
        "export default defineConfig({ plugins: [] })\n",
        encoding="utf-8",
    )
    ensure_vite_allowed_hosts(tmp_path, ["preview.kiwiai.shivamio.in"])
    text = cfg.read_text(encoding="utf-8")
    assert "allowedHosts" in text
    assert "preview.kiwiai.shivamio.in" in text


def test_creates_config_when_missing(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"todo"}', encoding="utf-8")
    ensure_vite_allowed_hosts(tmp_path, True)
    cfg = tmp_path / "vite.config.ts"
    assert cfg.exists()
    assert "allowedHosts: true" in cfg.read_text(encoding="utf-8")
