"""JSON Schema sanitize + tool-call aggregation helpers (finance Gemini loop)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

STRIP_KEYS = frozenset(
    {
        "additionalProperties",
        "$schema",
        "$defs",
        "default",
        "examples",
        "title",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "pattern",
        "format",
        "uniqueItems",
    }
)


def resolve_and_sanitize(schema: Any, defs: dict[str, Any]) -> Any:
    if not schema or not isinstance(schema, dict):
        if isinstance(schema, list):
            return [resolve_and_sanitize(item, defs) for item in schema]
        return schema

    if isinstance(schema.get("$ref"), str):
        ref_path = schema["$ref"]
        match = None
        if ref_path.startswith("#/$defs/"):
            match = ref_path[len("#/$defs/") :]
        elif ref_path.startswith("#/definitions/"):
            match = ref_path[len("#/definitions/") :]
        if match and match in defs:
            siblings = {k: v for k, v in schema.items() if k != "$ref"}
            return resolve_and_sanitize({**defs[match], **siblings}, defs)
        return {"type": "string", "description": schema.get("description") or ""}

    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key in STRIP_KEYS:
            continue
        cleaned[key] = resolve_and_sanitize(value, defs)

    if cleaned.get("type") == "object" and "properties" not in cleaned:
        cleaned["properties"] = {}
    return cleaned


def tool_to_openai_declaration(tool: dict[str, Any]) -> dict[str, Any]:
    full_schema = tool.get("inputSchema") or {}
    defs = full_schema.get("$defs") or full_schema.get("definitions") or {}
    sanitized_props = resolve_and_sanitize(full_schema.get("properties") or {}, defs)
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description") or "",
            "parameters": {
                "type": "object",
                "properties": sanitized_props,
                "required": full_schema.get("required") or [],
            },
        },
    }


def extract_first_json_object(s: str) -> str | None:
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def parse_tool_arguments(args_str: str) -> dict[str, Any]:
    trimmed = (args_str or "").strip()
    if not trimmed:
        return {}
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        first = extract_first_json_object(trimmed)
        if first:
            try:
                return json.loads(first)
            except json.JSONDecodeError:
                pass
        logger.error("Failed to parse tool arguments: %s", args_str[:200])
        return {}


class ToolCallAggregator:
    """Accumulate streaming tool_call deltas; handle Gemini index reuse."""

    def __init__(self) -> None:
        self._by_id: dict[str, dict[str, Any]] = {}
        self._last_id_by_index: dict[int, str] = {}
        self._synth = 0

    def _synth_id(self) -> str:
        self._synth += 1
        return f"call_{int(time.time() * 1000):x}_{self._synth:x}"

    def add_delta(self, tc: Any) -> None:
        idx = getattr(tc, "index", None)
        if idx is None and isinstance(tc, dict):
            idx = tc.get("index", 0)
        idx = int(idx) if idx is not None else 0

        fn = getattr(tc, "function", None) or (tc.get("function") if isinstance(tc, dict) else None)
        name_frag = ""
        args_frag = ""
        if fn is not None:
            name_frag = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else "") or ""
            args_frag = getattr(fn, "arguments", None) or (fn.get("arguments") if isinstance(fn, dict) else "") or ""

        call_id = getattr(tc, "id", None) or (tc.get("id") if isinstance(tc, dict) else None)

        if not call_id:
            mapped = self._last_id_by_index.get(idx)
            if mapped:
                prev = self._by_id.get(mapped)
                if (
                    name_frag
                    and prev
                    and prev["function"]["name"]
                    and prev["function"]["name"] != name_frag
                    and len(prev["function"]["arguments"]) > 0
                ):
                    call_id = self._synth_id()
                    self._last_id_by_index[idx] = call_id
                else:
                    call_id = mapped

        if not call_id:
            call_id = self._synth_id()
            self._last_id_by_index[idx] = call_id

        agg = self._by_id.get(call_id)
        if not agg:
            agg = {
                "id": call_id,
                "type": "function",
                "function": {"name": name_frag, "arguments": ""},
            }
            self._by_id[call_id] = agg
            self._last_id_by_index[idx] = call_id

        if name_frag:
            if not agg["function"]["name"]:
                agg["function"]["name"] = name_frag
            elif (
                agg["function"]["name"] != name_frag
                and len(agg["function"]["arguments"]) > 0
            ):
                split_id = self._synth_id()
                self._last_id_by_index[idx] = split_id
                self._by_id[split_id] = {
                    "id": split_id,
                    "type": "function",
                    "function": {"name": name_frag, "arguments": args_frag},
                }
                return

        if args_frag:
            agg["function"]["arguments"] += args_frag

    def to_array(self) -> list[dict[str, Any]]:
        return list(self._by_id.values())


def clip_tool_content(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n\n[Truncated: tool output exceeded {max_chars} characters.]"


def filter_tools_for_agent(
    tools: list[dict[str, Any]], allowed: tuple[str, ...], agent_id: str
) -> list[dict[str, Any]]:
    if not allowed:
        return tools
    filtered = [t for t in tools if t["name"] in allowed]
    if not filtered and tools:
        logger.warning(
            '[Chat] Agent "%s" allowlist matched 0 of %s MCP tools; using all tools.',
            agent_id,
            len(tools),
        )
        return tools
    return filtered
