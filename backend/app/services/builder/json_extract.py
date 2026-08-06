"""Pure JSON extraction / validation for builder codegen — no I/O, eval-friendly."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class ProjectFile:
    path: str
    content: str


def extract_json_object(text: str) -> str | None:
    """
    Robust JSON object extraction — handles markdown fences, preamble text, etc.
    Mirrors backend-1 extractJSON algorithm for parity.
    """
    cleaned = text.replace("```json", "").replace("```", "").strip()
    # Also strip residual fence language tags left by replace order
    cleaned = cleaned.replace("```", "").strip()

    start_idx = cleaned.find("{")
    if start_idx == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    end_idx = -1

    for i in range(start_idx, len(cleaned)):
        ch = cleaned[i]

        if escape:
            escape = False
            continue

        if ch == "\\" and in_string:
            escape = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i
                break

    if end_idx == -1:
        return None
    return cleaned[start_idx : end_idx + 1]


def parse_and_validate_files(response_text: str) -> list[ProjectFile]:
    """Parse AI response into validated ProjectFile list. Raises ValueError on failure."""
    json_string = extract_json_object(response_text)
    if not json_string:
        raise ValueError("Invalid response format from AI — no JSON object found")

    try:
        parsed: dict[str, Any] = json.loads(json_string)
    except json.JSONDecodeError as e:
        raise ValueError("Invalid response format from AI — malformed JSON") from e

    files = parsed.get("files")
    if not files or not isinstance(files, list):
        raise ValueError("Invalid response format from AI — missing 'files' array")

    validated = [
        ProjectFile(path=f["path"], content=f["content"])
        for f in files
        if isinstance(f, dict)
        and isinstance(f.get("path"), str)
        and isinstance(f.get("content"), str)
    ]
    if not validated:
        raise ValueError("Invalid response format from AI — no valid file entries")
    return validated
