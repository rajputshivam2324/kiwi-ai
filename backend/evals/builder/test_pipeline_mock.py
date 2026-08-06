"""Offline eval: full builder pipeline with mocked LLM (no Gemini / FS / DB)."""

import asyncio

from app.services.builder.json_extract import ProjectFile
from app.services.builder.pipeline import PipelineAdapters, generate_project


FIXTURE_JSON = """
{"files":[
  {"path":"package.json","content":"{\\"name\\":\\"demo\\"}"},
  {"path":"src/App.tsx","content":"export default function App(){return null}"}
]}
"""


async def _mock_llm(system, user, *, on_retry=None, on_chunk=None):
    if on_chunk:
        on_chunk(FIXTURE_JSON)
    return FIXTURE_JSON


def test_pipeline_with_mock_llm():
    events = []

    async def run():
        result = await generate_project(
            project_id="job_eval_1",
            prompt="Build a demo",
            on_event=lambda e, d: events.append((e, d)),
            adapters=PipelineAdapters(llm=_mock_llm),
        )
        return result

    result = asyncio.run(run())
    assert result.project_id == "job_eval_1"
    assert len(result.files) == 2
    assert result.preview_ready is False
    assert any(e[0] == "status" for e in events)
