/**
 * Agent Router: classifies user intent and selects the best agent.
 * Uses fast keyword matching instead of an LLM call to avoid wasting API quota.
 */

import { AGENTS, getDefaultAgent, type AgentDef } from "./agents.js";

/**
 * Keyword-based routing rules.
 * Each entry maps an agent ID to arrays of keyword patterns (case-insensitive).
 * First match wins, so order matters — more specific patterns first.
 */
const ROUTING_RULES: Array<{ agentId: string; patterns: RegExp[] }> = [
  {
    agentId: "technical_analyst",
    patterns: [
      /\b(rsi|macd|sma|ema|bollinger|adx|stochastic|williams\s*%?\s*r)\b/i,
      /\b(technical\s*(analysis|indicator|chart))\b/i,
      /\b(moving\s*average|trend\s*analysis|chart\s*pattern|support\s*and\s*resistance)\b/i,
      /\b(overbought|oversold|momentum\s*indicator)\b/i,
    ],
  },
  {
    agentId: "portfolio_tracker",
    patterns: [
      /\b(my\s*(portfolio|holdings|positions?|orders?|trades?|balance|margin))\b/i,
      /\b(show\s*(portfolio|holdings|positions?|order\s*book|trade\s*book))\b/i,
      /\b(order\s*(book|history|status))\b/i,
      /\b(trade\s*book|trade\s*history)\b/i,
      /\b(available\s*margin|portfolio\s*(tracker|summary|performance))\b/i,
    ],
  },
  {
    agentId: "stock_screener",
    patterns: [
      /\b(tell\s*me\s*about|search\s*(for\s*)?(stock|company|instrument))\b/i,
      /\b(fundamentals?|revenue|profit|p\/?e(\s*ratio)?|roe|roce|eps|debt.to.equity)\b/i,
      /\b(company\s*(info|details|overview|analysis))\b/i,
      /\b(financial\s*(health|data|details|analysis))\b/i,
      /\b(what\s*is\s+[a-z]+\s*(stock|company|share))\b/i,
      /\b(isin|lot\s*size|instrument\s*details)\b/i,
    ],
  },
  {
    agentId: "market_analyst",
    patterns: [
      /\b(price|ltp|quote|ohlc)\s*(of|for)?\b/i,
      /\b(current\s*price|last\s*traded?\s*price|market\s*price)\b/i,
      /\b(top\s*(gainers?|losers?)|most\s*active)\b/i,
      /\b(market\s*(overview|summary|data|update))\b/i,
      /\b(day\s*high|day\s*low|52\s*week|volume)\b/i,
      /\b(how\s*much\s*(is|does))\b/i,
      /\b(what\s*is\s*the\s*price)\b/i,
      /\b(historical\s*candle|candle\s*data)\b/i,
    ],
  },
  {
    // investment_advisor is the catch-all, but also matches explicit buy/sell intent
    agentId: "investment_advisor",
    patterns: [
      /\b(buy|sell|place\s*order|invest\s*in|should\s*i)\b/i,
      /\b(investment\s*(advice|recommendation|idea))\b/i,
      /\b(margin\s*check|order\s*place)\b/i,
    ],
  },
];

/**
 * Route user message to the best agent using fast keyword matching.
 * Falls back to investment_advisor for ambiguous queries.
 * Zero API calls — purely deterministic.
 */
export function routeToAgent(userMessage: string): AgentDef {
  const msg = userMessage.toLowerCase();

  for (const rule of ROUTING_RULES) {
    for (const pattern of rule.patterns) {
      if (pattern.test(msg)) {
        const agent = AGENTS.find((a) => a.id === rule.agentId);
        if (agent) {
          console.log(
            `[Router] Keyword match: "${userMessage.substring(0, 50)}..." → ${agent.id} (pattern: ${pattern.source})`
          );
          return agent;
        }
      }
    }
  }

  console.log(`[Router] No keyword match, falling back to investment_advisor`);
  return getDefaultAgent();
}
