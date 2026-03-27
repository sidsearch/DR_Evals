"""
Minimal agent loop.

Flow per turn:
  1. Append user message to history.
  2. Call Claude with tools, streaming the response.
  3. Collect assistant message (text + tool_use blocks).
  4. If tool calls present: execute them, append results, go to 2.
  5. Otherwise: return final text to the CLI.
"""

import anthropic
from typing import Iterator
from tools import dispatch, schemas

MODEL = "claude-opus-4-6"

SYSTEM = """\
You are a minimal coding agent running in a terminal.
You can read, write, and edit files, run shell commands, search for files and text.
Work step-by-step. When you are done, give a concise summary of what you did.
Current working directory: {cwd}
"""


class Agent:
    def __init__(self, model: str = MODEL, cwd: str = "."):
        self.client = anthropic.Anthropic()
        self.model = model
        self.cwd = cwd
        self.history: list[dict] = []

    def _system(self) -> str:
        import os
        return SYSTEM.format(cwd=os.path.abspath(self.cwd))

    def stream_turn(self, user_message: str) -> Iterator[str]:
        """
        Process one user turn. Yields text chunks as they arrive.
        Handles multiple tool-call rounds internally (agentic loop).
        """
        self.history.append({"role": "user", "content": user_message})

        while True:
            # --- call the model ---
            assistant_content: list[dict] = []
            current_text = ""

            with self.client.messages.stream(
                model=self.model,
                system=self._system(),
                messages=self.history,
                tools=schemas(),
                max_tokens=8096,
            ) as stream:
                for event in stream:
                    # text delta
                    if (
                        event.type == "content_block_delta"
                        and event.delta.type == "text_delta"
                    ):
                        current_text += event.delta.text
                        yield event.delta.text

                # Grab the final message to inspect tool use
                final = stream.get_final_message()

            # Build assistant content list
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

            # Collect tool calls
            tool_calls = [b for b in final.content if b.type == "tool_use"]

            if not tool_calls:
                # No tools → we're done
                break

            # --- execute tools ---
            tool_results = []
            for call in tool_calls:
                yield f"\n\n[tool: {call.name}({_fmt_inputs(call.input)})]\n"
                result = dispatch(call.name, call.input)
                # Yield a preview (first 400 chars)
                preview = result if len(result) <= 400 else result[:400] + "…"
                yield preview + "\n"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": result,
                })

            # Feed results back for the next iteration
            self.history.append({"role": "user", "content": tool_results})

    def reset(self):
        self.history.clear()


def _fmt_inputs(inputs: dict) -> str:
    """Compact single-line representation of tool inputs."""
    parts = []
    for k, v in inputs.items():
        sv = str(v)
        if len(sv) > 60:
            sv = sv[:57] + "..."
        parts.append(f"{k}={sv!r}")
    return ", ".join(parts)
