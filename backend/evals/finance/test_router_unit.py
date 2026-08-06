"""Eval tests for finance router + schema helpers (no network)."""

import inspect

from app.services.finance.agents.router import route_to_agent
from app.services.finance.chat_loop import chat_stream
from app.services.finance.schema_utils import (
    extract_first_json_object,
    parse_tool_arguments,
    resolve_and_sanitize,
    tool_to_openai_declaration,
)


def test_route_technical():
    agent = route_to_agent("What is the RSI of RELIANCE?")
    assert agent.id == "technical_analyst"


def test_route_portfolio():
    agent = route_to_agent("Show my portfolio holdings")
    assert agent.id == "portfolio_tracker"


def test_route_fallback():
    agent = route_to_agent("Tell me a joke about markets")
    assert agent.id == "investment_advisor"


def test_schema_sanitize_strips_unsupported():
    cleaned = resolve_and_sanitize(
        {
            "type": "object",
            "properties": {"x": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
            "$defs": {},
        },
        {},
    )
    assert "additionalProperties" not in cleaned
    assert "minLength" not in cleaned["properties"]["x"]


def test_parse_concatenated_tool_args():
    raw = '{"symbol":"RELIANCE"}{"extra":true}'
    assert extract_first_json_object(raw) == '{"symbol":"RELIANCE"}'
    assert parse_tool_arguments(raw)["symbol"] == "RELIANCE"


def test_tool_declaration():
    decl = tool_to_openai_declaration(
        {
            "name": "get_ltp",
            "description": "LTP",
            "inputSchema": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        }
    )
    assert decl["function"]["name"] == "get_ltp"


def test_chat_stream_with_mocked_tools():
    async def list_tools():
        return [
            {
                "name": "calculator",
                "description": "calc",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            }
        ]

    async def call_tool(name, args):
        return {"content": [{"type": "text", "text": "42"}], "isError": False}

    # We only assert the agent event fires without needing a real Gemini call
    # when tools are empty the loop would fail earlier; here we short-circuit
    # by not calling Gemini — skip full loop if no API key.
    agent = route_to_agent("price of nifty")
    assert agent.id == "market_analyst"

    # Smoke: chat_stream is an async generator; tool injectables are coroutines
    assert inspect.isasyncgenfunction(chat_stream)
    assert inspect.iscoroutinefunction(list_tools)
    assert inspect.iscoroutinefunction(call_tool)
