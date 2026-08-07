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


def test_replace_existing_allowed_hosts(tmp_path: Path) -> None:
    cfg = tmp_path / "vite.config.ts"
    cfg.write_text(
        "export default defineConfig({ server: { allowedHosts: ['localhost'] } })\n",
        encoding="utf-8",
    )
    ensure_vite_allowed_hosts(tmp_path, True)
    text = cfg.read_text(encoding="utf-8")
    assert "allowedHosts: true" in text
