"""
Finance agentic tool loop — core logic injectable for evals.

Yields SSE-shaped dicts: {type: agent|text, ...}
Tool execution + LLM are injectable so evals can mock MCP + Gemini.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Awaitable
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.finance.agents.router import route_to_agent
from app.services.finance.mcp_client import (
    execute_mcp_tool,
    get_mcp_tools,
    is_mcp_connected,
)
from app.services.finance.schema_utils import (
    ToolCallAggregator,
    clip_tool_content,
    filter_tools_for_agent,
    parse_tool_arguments,
    tool_to_openai_declaration,
)
from app.services.gemini_client import stream_chat_with_retry

logger = logging.getLogger(__name__)

ToolFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
ListToolsFn = Callable[[], Awaitable[list[dict[str, Any]]]]


def _ist_date_context() -> str:
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    current_date = now.strftime("%A, %d %B %Y")
    current_time = now.strftime("%I:%M %p")
    return (
        f"\n\nIMPORTANT — CURRENT DATE & TIME CONTEXT:\n"
        f"Today's date is {current_date}.\n"
        f"Current time (IST): {current_time}.\n"
        f'You MUST use this date as "today" for ALL analysis, comparisons, and market data references.\n'
        f'Do NOT assume any other date. Any reference to "today", "current", "now", or "latest" means {current_date}.\n'
    )


async def chat_stream(
    messages: list[dict[str, str]],
    *,
    list_tools: ListToolsFn | None = None,
    call_tool: ToolFn | None = None,
    connected_check: Callable[[], bool] | None = None,
    max_tool_rounds: int = 10,
) -> AsyncIterator[dict[str, Any]]:
    """
    Agentic finance chat. Pure enough for evals when list_tools/call_tool are mocked.
    messages: [{role: user|model|assistant, content: str}, ...]
    """
    if not messages:
        raise ValueError("At least one message is required")

    settings = get_settings()
    list_tools = list_tools or get_mcp_tools
    call_tool = call_tool or execute_mcp_tool
    connected_check = connected_check or is_mcp_connected

    last_user = next(
        (m for m in reversed(messages) if m.get("role") == "user"),
        None,
    )
    agent = route_to_agent((last_user or {}).get("content") or "")
    logger.info("[Chat] Routed to agent: %s %s (%s)", agent.emoji, agent.name, agent.id)
    yield {
        "type": "agent",
        "agent": {"id": agent.id, "name": agent.name, "emoji": agent.emoji},
    }

    try:
        mcp_tools = await list_tools()
        if not mcp_tools:
            raise RuntimeError("Groww MCP server returned no tools.")
        tool_definitions = filter_tools_for_agent(
            mcp_tools, agent.allowed_tools, agent.id
        )
    except Exception as e:
        raise RuntimeError(f"Groww MCP is not connected. Error: {e}") from e

    tools = [tool_to_openai_declaration(t) for t in tool_definitions]

    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": agent.system_prompt + _ist_date_context()}
    ]
    for msg in messages:
        role = "assistant" if msg.get("role") == "model" else msg.get("role")
        conversation.append({"role": role, "content": msg.get("content", "")})

    last_text = ""
    round_i = 0

    while round_i < max_tool_rounds:
        if round_i > 0 and settings.gemini_tool_round_delay_ms > 0:
            await asyncio.sleep(settings.gemini_tool_round_delay_ms / 1000.0)

        current_text = ""
        current_reasoning = ""
        tool_agg = ToolCallAggregator()
        displayed = f"{last_text}\n\n" if last_text else ""
        is_thinking = False

        async for chunk in stream_chat_with_retry(
            messages=conversation,
            model=settings.llm_model,
            temperature=0.4,
            max_tokens=settings.max_tokens,
            tools=tools,
        ):
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                if not is_thinking:
                    displayed += "_Thinking..._\n\n> "
                    is_thinking = True
                current_reasoning += reasoning
                displayed += reasoning.replace("\n", "\n> ")
                yield {"type": "text", "content": displayed, "overwrite": True}

            if delta.content:
                if is_thinking and current_text == "":
                    displayed += "\n\n---\n\n"
                    is_thinking = False
                current_text += delta.content
                displayed += delta.content
                yield {"type": "text", "content": displayed, "overwrite": True}

            tool_calls = getattr(delta, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    tool_agg.add_delta(tc)

        function_calls = tool_agg.to_array()

        if current_reasoning or current_text or function_calls:
            last_text = displayed
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": current_text or "",
            }
            if function_calls:
                assistant_msg["tool_calls"] = function_calls
            conversation.append(assistant_msg)

        if not function_calls:
            return

        async def _run_one(fc: dict[str, Any]) -> dict[str, str]:
            name = fc["function"]["name"]
            args = parse_tool_arguments(fc["function"].get("arguments") or "")
            if not connected_check() and call_tool is execute_mcp_tool:
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": "Error: Groww MCP is not connected. Cannot execute tool.",
                        }
                    ],
                    "isError": True,
                }
            else:
                result = await call_tool(name, args)
            joined = "\n".join(
                c.get("text", "")
                for c in result.get("content") or []
                if c.get("type") == "text"
            ) or str(result)
            result_text = clip_tool_content(
                joined, settings.gemini_max_tool_result_chars
            )
            return {"tool_call_id": fc["id"], "name": name, "resultText": result_text}

        tool_responses = await asyncio.gather(*[_run_one(fc) for fc in function_calls])
        for tr in tool_responses:
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": tr["tool_call_id"],
                    "content": tr["resultText"],
                }
            )

        round_i += 1
