"""Prompt contract tests — persona, CoT, few-shot markers present."""

from app.services.builder import prompts as builder
from app.services.finance.agents import prompts as finance
from app.services.research import prompts as research


def test_builder_persona_and_internal_cot():
    assert "Kiwi Builder" in builder.NEW_PROJECT_SYSTEM
    assert "plan internally" in builder.NEW_PROJECT_SYSTEM.lower()
    assert "FEW-SHOT" in builder.NEW_PROJECT_SYSTEM
    assert "npm run build" in builder.FIX_BUILD_SYSTEM
    assert "think step-by-step internally" in builder.CHAT_SYSTEM.lower()
    assert "Few-shot" in builder.CHAT_SYSTEM or "few-shot" in builder.CHAT_SYSTEM.lower()


def test_research_cot_and_citation_few_shot():
    assert "Kiwi Research" in research.SYSTEM_PROMPT
    assert "Internal reasoning workflow" in research.SYSTEM_PROMPT
    assert "Few-shot citation" in research.SYSTEM_PROMPT
    assert "{tool_results}" in research.SYSTEM_PROMPT
    assert "{context}" in research.SYSTEM_PROMPT


def test_finance_persona_cot_and_order_few_shot():
    assert "Kiwi Finance" in finance.FINANCE_CORE_PERSONA
    assert "CoT" in finance.FINANCE_CORE_PERSONA or "think internally" in finance.FINANCE_CORE_PERSONA.lower()
    assert "few-shot" in finance.ORDER_CONFIRMATION_FEW_SHOT.lower()
    assert "MCP tools only" in finance.FINANCE_CORE_PERSONA or "MCP tools" in finance.FINANCE_CORE_PERSONA
    advisor = finance.get_agent_system_prompt("investment_advisor")
    assert "confirm" in advisor.lower()
    assert "Mandatory structure" in finance.STOCK_ANALYSIS_SECTIONS or "Company Overview" in finance.STOCK_ANALYSIS_SECTIONS


def test_build_prompts_follow_up_includes_files():
    sys_p, user = builder.build_prompts("fix navbar", [{"path": "a.tsx", "content": "x"}])
    assert sys_p == builder.FOLLOW_UP_SYSTEM
    assert "a.tsx" in user
    assert "FOLLOW-UP" in user
