"""
Deep Research Agent — HTTP API server.

Endpoints:
  POST /research/stream  — Server-Sent Events: streams output in real time
  POST /research         — Blocking: waits for the full report, returns JSON
  GET  /health           — Health check

Start the server:
    pip install fastapi uvicorn
    uvicorn api_server:app --reload --port 8000

Environment variables (at least one search key required):
    ANTHROPIC_API_KEY   — required
    TAVILY_API_KEY      — recommended search provider
    SERPAPI_API_KEY     — fallback search provider
"""

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Ensure the example directory and harness are importable
_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_DIR))

from research_agent import ResearchAgent

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Deep Research Agent",
    description="API wrapper around the deep-research agent. "
                "POST a topic, receive a streamed Markdown report.",
    version="1.0.0",
)

_executor = ThreadPoolExecutor(max_workers=4)  # one thread per concurrent research job


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ResearchRequest(BaseModel):
    topic: str = Field(..., description="The topic to research", min_length=3)
    output_dir: str = Field(
        default="/tmp/research_reports",
        description="Directory where the Markdown report will be saved",
    )


class ResearchResponse(BaseModel):
    topic: str
    report_path: str
    output: str
    input_tokens: int
    output_tokens: int


# ---------------------------------------------------------------------------
# Shared helper: run the synchronous agent in a background thread
# ---------------------------------------------------------------------------

def _build_prompt(topic: str, output_dir: str) -> str:
    return (
        f"Research this topic comprehensively: **{topic}**\n\n"
        f"Follow the five-phase methodology in your system instructions.\n"
        f"Save the finished report to: {output_dir}/report_<slug>.md\n"
        f"where <slug> is a short kebab-case version of the topic."
    )


async def _stream_research(topic: str, output_dir: str) -> AsyncIterator[str]:
    """
    Bridge the synchronous ResearchAgent generator to an async iterator.

    Each yielded value is an SSE-formatted string:
      data: {"text": "...chunk..."}\n\n   — during streaming
      data: {"done": true, ...stats}\n\n  — final event
      data: {"error": "..."}\n\n          — on failure
    """
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _run() -> None:
        """Runs in the thread pool. Pushes SSE strings onto the queue."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        try:
            agent = ResearchAgent(output_dir=output_dir)
            prompt = _build_prompt(topic, output_dir)
            for chunk in agent.stream_turn(prompt):
                payload = json.dumps({"text": chunk})
                loop.call_soon_threadsafe(queue.put_nowait, f"data: {payload}\n\n")
            # Final stats event
            stats = json.dumps({
                "done": True,
                "input_tokens": agent.turn_input_tokens,
                "output_tokens": agent.turn_output_tokens,
            })
            loop.call_soon_threadsafe(queue.put_nowait, f"event: done\ndata: {stats}\n\n")
        except Exception as exc:
            err = json.dumps({"error": str(exc)})
            loop.call_soon_threadsafe(queue.put_nowait, f"event: error\ndata: {err}\n\n")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

    loop.run_in_executor(_executor, _run)

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/research/stream", summary="Stream research output via Server-Sent Events")
async def research_stream(req: ResearchRequest) -> StreamingResponse:
    """
    Stream research output as Server-Sent Events.

    The client receives a stream of events:
    - `data` events during research (each carries `{"text": "..."}`)
    - A final `done` event with token usage stats
    - An `error` event if something goes wrong

    Example with curl:
        curl -N -X POST http://localhost:8000/research/stream \\
             -H "Content-Type: application/json" \\
             -d '{"topic": "fusion energy advances 2024"}'
    """
    return StreamingResponse(
        _stream_research(req.topic, req.output_dir),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # prevents nginx from buffering SSE
        },
    )


@app.post("/research", response_model=ResearchResponse, summary="Run research and return the full report")
async def research_sync(req: ResearchRequest) -> ResearchResponse:
    """
    Blocking endpoint: runs the full research session and returns the report as JSON.

    Use this for short topics or when you don't need streaming.
    For long research tasks the connection may time out — use /research/stream instead.
    """
    loop = asyncio.get_event_loop()
    Path(req.output_dir).mkdir(parents=True, exist_ok=True)

    def _run() -> tuple[str, int, int]:
        agent = ResearchAgent(output_dir=req.output_dir)
        output = agent.run(_build_prompt(req.topic, req.output_dir))
        return output, agent.turn_input_tokens, agent.turn_output_tokens

    try:
        output, in_tok, out_tok = await loop.run_in_executor(_executor, _run)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Find the report file if the agent wrote one
    slug = req.topic.lower().replace(" ", "-")[:40]
    report_path = f"{req.output_dir}/report_{slug}.md"

    return ResearchResponse(
        topic=req.topic,
        report_path=report_path,
        output=output,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )
