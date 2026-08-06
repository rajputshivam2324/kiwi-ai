"""Install, build, and dev-server health checks for generated projects."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


async def _run_cmd(
    cmd: str,
    cwd: Path,
    timeout: float = 180.0,
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", f"Command timed out after {timeout}s: {cmd}"
    stdout = (stdout_b or b"").decode(errors="replace")
    stderr = (stderr_b or b"").decode(errors="replace")
    return proc.returncode or 0, stdout, stderr


def _clip_log(text: str, max_chars: int = 6000) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars // 2] + "\n\n...[truncated]...\n\n" + text[-max_chars // 2 :]


async def npm_install(project_path: Path) -> tuple[bool, str]:
    code, out, err = await _run_cmd("npm install --no-fund --no-audit", project_path, timeout=240)
    if code == 0:
        return True, ""
    log = _clip_log(f"npm install failed (exit {code})\n\nSTDERR:\n{err}\n\nSTDOUT:\n{out}")
    return False, log


async def npm_build(project_path: Path) -> tuple[bool, str]:
    pkg = project_path / "package.json"
    if not pkg.exists():
        return False, "Missing package.json"
    code, out, err = await _run_cmd("npm run build", project_path, timeout=180)
    if code == 0:
        return True, ""
    log = _clip_log(f"npm run build failed (exit {code})\n\nSTDERR:\n{err}\n\nSTDOUT:\n{out}")
    return False, log


async def wait_for_http(port: int, timeout: float = 45.0) -> bool:
    url = f"http://127.0.0.1:{port}/"
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(follow_redirects=True) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(url, timeout=2.0)
                if r.status_code < 500:
                    return True
            except Exception:
                pass
            await asyncio.sleep(1.5)
    return False


async def verify_project_build(project_path: Path) -> tuple[bool, str]:
    """npm install + vite build — catches most codegen errors before preview."""
    ok, log = await npm_install(project_path)
    if not ok:
        return False, log
    return await npm_build(project_path)
