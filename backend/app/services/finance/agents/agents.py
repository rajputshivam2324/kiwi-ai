"""Specialized finance agent definitions with composed system prompts."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.finance.agents.prompts import get_agent_system_prompt


@dataclass(frozen=True)
class AgentDef:
    id: str
    name: str
    emoji: str
    description: str
    system_prompt: str
    allowed_tools: tuple[str, ...]


def _agent(
    id: str,
    name: str,
    emoji: str,
    description: str,
    allowed_tools: tuple[str, ...],
) -> AgentDef:
    return AgentDef(
        id=id,
        name=name,
        emoji=emoji,
        description=description,
        system_prompt=get_agent_system_prompt(id),
        allowed_tools=allowed_tools,
    )


AGENTS: list[AgentDef] = [
    _agent(
        "market_analyst",
        "Market Analyst",
        "📊",
        "Handles market overview, current prices, top gainers/losers, and real-time market data.",
        (
            "get_ltp",
            "get_quotes_and_depth",
            "fetch_historical_candle_data",
            "fetch_market_movers_and_trending_stocks_funds",
            "resolve_market_time_and_calendar",
            "get_historical_candlestick_patterns",
            "calculator",
        ),
    ),
    _agent(
        "stock_screener",
        "Stock Screener",
        "🔍",
        "Searches for stocks, retrieves instrument details, and provides fundamental analysis of companies.",
        (
            "curate_symbols",
            "fetch_stocks_fundamental_data",
            "fetch_fundamentals_screener",
            "fetch_etf_screener",
            "fetch_technical_screener",
            "fetch_ipo_listings",
            "fetch_ipo_details",
            "get_mutualfund_details",
            "calculator",
        ),
    ),
    _agent(
        "technical_analyst",
        "Technical Analyst",
        "📈",
        "Calculates technical indicators and provides chart analysis.",
        (
            "fetch_historical_candle_data",
            "get_historical_technical_indicators",
            "get_historical_candlestick_patterns",
            "get_ltp",
            "get_quotes_and_depth",
            "resolve_market_time_and_calendar",
            "calculator",
        ),
    ),
    _agent(
        "portfolio_tracker",
        "Portfolio Tracker",
        "💼",
        "Tracks portfolio holdings, open positions, order status, trade history, and available margins.",
        (
            "get_equity_portfolio_holdings",
            "get_my_trading_positions_today",
            "get_specific_stock_position",
            "get_order_details",
            "get_available_margin_details",
            "calculate_equity_margin",
            "calculate_fno_margin",
            "calculator",
        ),
    ),
    _agent(
        "investment_advisor",
        "Investment Advisor",
        "🧠",
        "Provides holistic investment advice; fallback for ambiguous queries.",
        (),  # all tools
    ),
]


def get_agent_by_id(agent_id: str) -> AgentDef | None:
    return next((a for a in AGENTS if a.id == agent_id), None)


def get_default_agent() -> AgentDef:
    return get_agent_by_id("investment_advisor")  # type: ignore[return-value]
