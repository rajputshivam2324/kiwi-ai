"""Keyword intent router for finance agents — deterministic, zero API cost."""

from __future__ import annotations

import logging
import re

from app.services.finance.agents.agents import AGENTS, AgentDef, get_default_agent

logger = logging.getLogger(__name__)

ROUTING_RULES: list[tuple[str, list[re.Pattern[str]]]] = [
    (
        "technical_analyst",
        [
            re.compile(r"\b(rsi|macd|sma|ema|bollinger|adx|stochastic|williams\s*%?\s*r)\b", re.I),
            re.compile(r"\b(technical\s*(analysis|indicator|chart))\b", re.I),
            re.compile(
                r"\b(moving\s*average|trend\s*analysis|chart\s*pattern|support\s*and\s*resistance)\b",
                re.I,
            ),
            re.compile(r"\b(overbought|oversold|momentum\s*indicator)\b", re.I),
        ],
    ),
    (
        "portfolio_tracker",
        [
            re.compile(r"\b(my\s*(portfolio|holdings|positions?|orders?|trades?|balance|margin))\b", re.I),
            re.compile(r"\b(show\s*(portfolio|holdings|positions?|order\s*book|trade\s*book))\b", re.I),
            re.compile(r"\b(order\s*(book|history|status))\b", re.I),
            re.compile(r"\b(trade\s*book|trade\s*history)\b", re.I),
            re.compile(r"\b(available\s*margin|portfolio\s*(tracker|summary|performance))\b", re.I),
        ],
    ),
    (
        "stock_screener",
        [
            re.compile(r"\b(tell\s*me\s*about|search\s*(for\s*)?(stock|company|instrument))\b", re.I),
            re.compile(r"\b(fundamentals?|revenue|profit|p/?e(\s*ratio)?|roe|roce|eps|debt.to.equity)\b", re.I),
            re.compile(r"\b(company\s*(info|details|overview|analysis))\b", re.I),
            re.compile(r"\b(financial\s*(health|data|details|analysis))\b", re.I),
            re.compile(r"\b(what\s*is\s+[a-z]+\s*(stock|company|share))\b", re.I),
            re.compile(r"\b(isin|lot\s*size|instrument\s*details)\b", re.I),
        ],
    ),
    (
        "market_analyst",
        [
            re.compile(r"\b(price|ltp|quote|ohlc)\s*(of|for)?\b", re.I),
            re.compile(r"\b(current\s*price|last\s*traded?\s*price|market\s*price)\b", re.I),
            re.compile(r"\b(top\s*(gainers?|losers?)|most\s*active)\b", re.I),
            re.compile(r"\b(market\s*(overview|summary|data|update))\b", re.I),
            re.compile(r"\b(day\s*high|day\s*low|52\s*week|volume)\b", re.I),
            re.compile(r"\b(how\s*much\s*(is|does))\b", re.I),
            re.compile(r"\b(what\s*is\s*the\s*price)\b", re.I),
            re.compile(r"\b(historical\s*candle|candle\s*data)\b", re.I),
        ],
    ),
    (
        "investment_advisor",
        [
            re.compile(r"\b(buy|sell|place\s*order|invest\s*in|should\s*i)\b", re.I),
            re.compile(r"\b(investment\s*(advice|recommendation|idea))\b", re.I),
            re.compile(r"\b(margin\s*check|order\s*place)\b", re.I),
        ],
    ),
]


def route_to_agent(user_message: str) -> AgentDef:
    """Route user message to the best agent using keyword matching."""
    for agent_id, patterns in ROUTING_RULES:
        for pattern in patterns:
            if pattern.search(user_message):
                agent = next((a for a in AGENTS if a.id == agent_id), None)
                if agent:
                    logger.info(
                        "[Router] Keyword match → %s (pattern: %s)",
                        agent.id,
                        pattern.pattern,
                    )
                    return agent
    logger.info("[Router] No keyword match, falling back to investment_advisor")
    return get_default_agent()
