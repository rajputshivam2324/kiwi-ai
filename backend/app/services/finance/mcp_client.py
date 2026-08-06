"""Groww MCP client via stdio (npx mcp-remote). Real Groww only — no stubs."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


class GrowwMCPClient:
    def __init__(self) -> None:
        self._session: Any = None
        self._stack: AsyncExitStack | None = None
        self._cached_tools: list[dict[str, Any]] | None = None
        self._connect_lock = asyncio.Lock()
        self._connect_task: asyncio.Task | None = None
        self._last_connect_error: str | None = None

    def is_connected(self) -> bool:
        return self._session is not None

    def connection_status(self) -> dict[str, Any]:
        return {
            "connected": self.is_connected(),
            "connecting": self._connect_task is not None and not self._connect_task.done(),
            "tool_count": len(self._cached_tools or []),
            "last_error": self._last_connect_error,
        }

    def start_background_connect(self) -> None:
        """Kick off Groww OAuth/MCP connect without blocking API startup."""
        if get_settings().mcp_use_stub_tools:
            logger.warning("[MCP] Stub mode is disabled by product config; ignoring stub flag")
        if self.is_connected():
            return
        if self._connect_task and not self._connect_task.done():
            return
        self._connect_task = asyncio.create_task(self._connect_with_logging())

    async def _connect_with_logging(self) -> None:
        try:
            await self.connect()
        except Exception as e:
            self._last_connect_error = str(e)
            logger.error("[MCP] Background connect failed: %s", e)

    async def ensure_connected(self, timeout: float | None = None) -> None:
        """Wait until connected (or until timeout). Starts connect if idle."""
        settings = get_settings()
        timeout = timeout if timeout is not None else settings.mcp_connect_timeout_seconds

        if self.is_connected():
            return

        if not self._connect_task or self._connect_task.done():
            self.start_background_connect()

        if self._connect_task:
            try:
                await asyncio.wait_for(asyncio.shield(self._connect_task), timeout=timeout)
            except asyncio.TimeoutError as e:
                raise RuntimeError(
                    "Groww MCP is still connecting. Complete OAuth in the browser if prompted, then retry."
                ) from e

        if not self.is_connected():
            detail = self._last_connect_error or "Groww MCP is not connected"
            raise RuntimeError(detail)

    async def connect(self) -> None:
        async with self._connect_lock:
            if self._session:
                return
            try:
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client
            except ImportError as e:
                raise RuntimeError(
                    "mcp package required for Groww integration. pip install mcp"
                ) from e

            settings = get_settings()
            logger.info("[MCP] Connecting to Groww MCP server...")
            params = StdioServerParameters(
                command=settings.mcp_command,
                args=settings.mcp_args_list,
            )
            self._stack = AsyncExitStack()
            await self._stack.__aenter__()
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._session = session
            self._last_connect_error = None
            await self.refresh_tools()
            logger.info("[MCP] Connected — %s tools", len(self._cached_tools or []))

    async def disconnect(self) -> None:
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
            try:
                await self._connect_task
            except asyncio.CancelledError:
                pass
        if self._stack:
            try:
                await self._stack.aclose()
            except Exception:
                pass
        self._stack = None
        self._session = None
        self._cached_tools = None
        self._connect_task = None
        logger.info("[MCP] Disconnected")

    async def refresh_tools(self) -> None:
        if not self._session:
            self._cached_tools = []
            return
        result = await self._session.list_tools()
        self._cached_tools = []
        for t in result.tools:
            schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {}
            self._cached_tools.append(
                {
                    "name": t.name,
                    "description": getattr(t, "description", None),
                    "inputSchema": schema,
                }
            )
        logger.info(
            "[MCP] Loaded tools: %s",
            ", ".join(t["name"] for t in self._cached_tools),
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        await self.ensure_connected()
        if self._cached_tools is None and self._session:
            await self.refresh_tools()
        return list(self._cached_tools or [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_connected()
        logger.info("[MCP] Calling tool: %s %s", name, arguments)
        try:
            result = await self._session.call_tool(name, arguments)
            content = []
            for c in result.content or []:
                if hasattr(c, "text"):
                    content.append({"type": "text", "text": c.text})
                else:
                    content.append(
                        {"type": getattr(c, "type", "text"), **getattr(c, "__dict__", {})}
                    )
            return {"content": content, "isError": bool(getattr(result, "isError", False))}
        except Exception as e:
            msg = str(e)
            if "SSE stream disconnected" in msg or "terminated" in msg:
                logger.warning("[MCP] Benign SSE noise after tool %s — ignoring", name)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Tool {name} completed but SSE stream reset.",
                        }
                    ],
                    "isError": False,
                }
            logger.error("[MCP] Tool %s failed: %s", name, e)
            return {
                "content": [{"type": "text", "text": f"Error calling {name}: {msg}"}],
                "isError": True,
            }


_mcp: GrowwMCPClient | None = None


def get_mcp_client() -> GrowwMCPClient:
    global _mcp
    if _mcp is None:
        _mcp = GrowwMCPClient()
    return _mcp


async def get_mcp_tools() -> list[dict[str, Any]]:
    return await get_mcp_client().list_tools()


async def execute_mcp_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return await get_mcp_client().call_tool(name, args)


def is_mcp_connected() -> bool:
    return get_mcp_client().is_connected()


async def disconnect_mcp() -> None:
    await get_mcp_client().disconnect()
