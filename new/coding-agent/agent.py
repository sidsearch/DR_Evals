"""
Coding agent loop.

Flow per turn:
  1. Append user message to history.
  2. Call Claude with tools, streaming the response.
  3. Collect assistant message (text + tool_use blocks).
  4. If tool calls present: execute them, append results, go to 2.
  5. Otherwise: return final text to the CLI.
"""

import json
import subprocess
import anthropic
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Callable
from tools import dispatch, schemas

MODEL = "claude-opus-4-6"

SYSTEM = """\
You are a coding agent running in a terminal.
You can read, write, and edit files, run shell commands, search for files and text.

For complex, multi-step requests:
  1. Use task_create to break the work into discrete subtasks.
  2. Call task_update(id, "in_progress") before starting each task.
  3. Call task_update(id, "done") when each task is complete.
  4. Use task_list to review overall progress.

Work step-by-step. When you are done, give a concise summary of what you did.
Current working directory: {cwd}{git_info}
"""


class Agent:
    def __init__(
        self,
        model: str = MODEL,
        cwd: str = ".",
        bash_approval_fn: Callable[[str], bool] | None = None,
        max_tokens: int = 8096,
        trace_file: str | None = None,
    ):
        self.client = anthropic.Anthropic()
        self.model = model
        self.cwd = cwd
        self.bash_approval_fn = bash_approval_fn
        self.max_tokens = max_tokens
        self.history: list[dict] = []
        # Cumulative token counts for the session
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        # Per-turn token counts (reset at start of each stream_turn)
        self.turn_input_tokens = 0
        self.turn_output_tokens = 0
        # Optional JSONL trace file
        self._trace_path = Path(trace_file) if trace_file else None
        if self._trace_path:
            self._trace_path.parent.mkdir(parents=True, exist_ok=True)

    def _system(self) -> str:
        import os
        cwd = os.path.abspath(self.cwd)
        git_info = ""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, cwd=cwd,
            )
            if result.returncode == 0:
                branch = subprocess.run(
                    ["git", "branch", "--show-current"],
                    capture_output=True, text=True, cwd=cwd,
                ).stdout.strip()
                if branch:
                    git_info = f"\nGit branch: {branch}"
        except Exception:
            pass
        return SYSTEM.format(cwd=cwd, git_info=git_info)

    def stream_turn(self, user_message: str) -> Iterator[str]:
        """
        Process one user turn. Yields text chunks as they arrive.
        Handles multiple tool-call rounds internally (agentic loop).
        Updates self.turn_input_tokens / self.turn_output_tokens when done.
        """
        self.turn_input_tokens = 0
        self.turn_output_tokens = 0
        self._trace("user_message", content=user_message)
        self.history.append({"role": "user", "content": user_message})

        while True:
            # --- call the model ---
            with self.client.messages.stream(
                model=self.model,
                system=self._system(),
                messages=self.history,
                tools=schemas(),
                max_tokens=self.max_tokens,
            ) as stream:
                for event in stream:
                    if (
                        event.type == "content_block_delta"
                        and event.delta.type == "text_delta"
                    ):
                        yield event.delta.text

                final = stream.get_final_message()

            # Accumulate token usage
            if hasattr(final, "usage") and final.usage:
                self.turn_input_tokens += final.usage.input_tokens
                self.turn_output_tokens += final.usage.output_tokens
                self.total_input_tokens += final.usage.input_tokens
                self.total_output_tokens += final.usage.output_tokens

            # Build assistant content list
            assistant_content: list[dict] = []
            for block in final.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            self.history.append({"role": "assistant", "content": assistant_content})

            tool_calls = [b for b in final.content if b.type == "tool_use"]

            if not tool_calls:
                break

            # --- execute tools ---
            tool_results = []
            for call in tool_calls:
                yield f"\n\n[tool: {call.name}({_fmt_inputs(call.input)})]\n"
                result = dispatch(
                    call.name,
                    call.input,
                    approval_fn=self.bash_approval_fn,
                )
                self._trace(
                    "tool_call",
                    tool=call.name,
                    inputs=call.input,  # already a dict at runtime
                    result_preview=result[:400] if len(result) > 400 else result,
                )
                preview = result if len(result) <= 400 else result[:400] + "…"
                yield preview + "\n"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": result,
                })

            self.history.append({"role": "user", "content": tool_results})

    def compact_history(self) -> str:
        """
        Summarize the conversation history into a compact synthetic exchange.
        Replaces self.history with a 2-message summary to free up context space.
        Returns the summary text.
        """
        if not self.history:
            return "History is empty, nothing to compact."

        summarize_messages = self.history + [{
            "role": "user",
            "content": (
                "Summarize our conversation so far into a compact context block. "
                "Include: the original request, what was done, any key file changes, "
                "and the current state. Be concise but complete enough to continue seamlessly."
            ),
        }]
        response = self.client.messages.create(
            model=self.model,
            system="You are summarizing a coding session. Produce a compact, information-dense summary.",
            messages=summarize_messages,
            max_tokens=2000,
        )
        first = response.content[0]
        summary = first.text if hasattr(first, "text") else str(first)
        old_count = len(self.history)
        self.history = [
            {
                "role": "user",
                "content": f"[Conversation compacted — {old_count} messages summarized]\n\n{summary}",
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Got it. I have the context from our previous work and am ready to continue."}],
            },
        ]
        return summary

    def _trace(self, event: str, **kwargs) -> None:
        """Append a JSONL trace entry to the trace file (if configured)."""
        if not self._trace_path:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **kwargs,
        }
        with self._trace_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def reset(self):
        self.history.clear()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.turn_input_tokens = 0
        self.turn_output_tokens = 0


def _fmt_inputs(inputs: dict) -> str:
    """Compact single-line representation of tool inputs."""
    parts = []
    for k, v in inputs.items():
        sv = str(v)
        if len(sv) > 60:
            sv = sv[:57] + "..."
        parts.append(f"{k}={sv!r}")
    return ", ".join(parts)
