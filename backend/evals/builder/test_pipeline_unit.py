"""Eval-friendly unit tests for builder JSON extract + prompt builders."""

from app.services.builder.json_extract import extract_json_object, parse_and_validate_files
from app.services.builder.prompts import build_prompts


def test_extract_json_with_fences():
    text = 'Here you go:\n```json\n{"files":[{"path":"a.ts","content":"x"}]}\n```\n'
    raw = extract_json_object(text)
    assert raw is not None
    files = parse_and_validate_files(text)
    assert len(files) == 1
    assert files[0].path == "a.ts"


def test_extract_json_balanced_braces_in_strings():
    text = '{"files":[{"path":"a.ts","content":"const o = {a:1};"}]}'
    files = parse_and_validate_files(text)
    assert "{" in files[0].content


def test_build_prompts_new_vs_followup():
    sys_new, user_new = build_prompts("Build a todo app")
    assert "JSON-only" in sys_new
    assert "todo app" in user_new

    sys_fu, user_fu = build_prompts(
        "Fix the bug",
        existing_files=[{"path": "src/App.tsx", "content": "export default () => null"}],
    )
    assert "modify existing" in sys_fu.lower() or "existing" in sys_fu.lower()
    assert "src/App.tsx" in user_fu
