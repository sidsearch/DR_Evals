# coding-agent — Design Document

**Version:** 1.1  
**Status:** Draft for discussion  
**References:** [Harness Design for Long-Running Apps — Anthropic Engineering](https://www.anthropic.com/engineering/harness-design-long-running-apps)

---

## 1. What this is

A terminal-native coding agent built directly on the Anthropic Messages API (and optionally AWS Bedrock). The core idea is simple: give a language model a set of tools for reading, writing, and executing code, then loop until it has nothing more to do.

This is not a framework wrapper. There is no LangChain, no LlamaIndex, no AutoGen. Every abstraction layer in the codebase was written here, which means we understand all of it and can change all of it.

---

## 2. Architecture walkthrough

### 2.1 The agentic loop (`agent.py`)

The central mechanism is a `while True` loop inside `Agent.stream_turn`:

```
user message
    → call model (streaming)
    → collect response: text blocks + tool_use blocks
    → if tool_use blocks exist:
        execute each tool
        append results
        loop back to model
    → if no tool_use blocks: done, return
```

This is the standard "ReAct" pattern. The model reasons, acts, observes the result, reasons again. There is no predefined plan — the model decides at each step what to do next.

The loop handles multiple rounds per user turn automatically. A single prompt like "refactor this module and run the tests" might trigger ten or more tool calls before the model returns a final response.

### 2.2 Tool system (`tools.py`, `tool_registry.py`)

There are two layers:

**Built-in tools** are defined directly in `tools.py` as plain functions alongside their JSON schemas. These are the core filesystem and shell operations:

| Tool | What it does |
|------|-------------|
| `read_file` | Paginated file reading (offset/limit) |
| `write_file` | Full file write with undo snapshot |
| `edit_file` | String replacement; `replace_all` flag for bulk edits |
| `undo_edit` | Stack-based undo — pop one edit at a time, as many times as needed |
| `bash` | Shell execution with optional approval gate |
| `find_files` | Glob search |
| `grep` | Regex search across files |
| `ls` | Directory listing |
| `task_create / task_update / task_list` | In-memory task tracking |

**Plugin tools** are loaded from the `plugins/` directory at startup (and on `/reload`). Any `.py` file with `@tool`-decorated functions is picked up automatically. The `@tool` decorator builds the JSON schema from Python type hints and Google-style docstrings — no schema boilerplate required.

### 2.3 CLI and interaction modes (`cli.py`, `tui.py`, `repl_dispatch.py`)

Three ways to run:

- **One-shot**: `python cli.py "prompt"` — runs the agent, prints output, exits
- **REPL**: interactive loop with `prompt_toolkit` (history, tab completion, slash commands)
- **TUI**: full-screen `Textual` UI with a scrollable transcript and bottom input bar

Slash commands (`/compact`, `/reset`, `/cost`, `/undo`, `/reload`, etc.) are handled in `repl_dispatch.py`, which is shared between the REPL and TUI so behavior is consistent.

### 2.4 Observability

- **Token tracking**: cumulative and per-turn input/output tokens; estimated cost displayed after each turn
- **JSONL tracing**: `--trace trace.jsonl` logs every tool call with timestamp, inputs, and a result preview — useful for debugging and evaluation
- **History compaction**: `/compact` summarises the conversation into a synthetic two-message exchange when the context is getting long

### 2.5 Provider support

By default the agent calls `anthropic.Anthropic()`. Pass `--bedrock` to switch to `anthropic.AnthropicBedrock()`, which uses the standard AWS credential chain. The rest of the code is identical — the two clients share the same interface.

---

## 3. What works well

**The loop is correct and minimal.** There is very little code between a user message and the model's response. That makes it easy to reason about, easy to debug, and easy to extend.

**Streaming is first-class.** `stream_turn` is a generator — chunks arrive as they are produced, which makes the REPL feel responsive even on long tasks.

**The plugin system is genuinely low-friction.** Drop a file in `plugins/`, decorate functions with `@tool`, and they are available immediately. No registration, no config files, no schema writing. This is the right API for extensibility.

**Bash approval gate is injected, not hardcoded.** The `bash_approval_fn` parameter means the same `Agent` class works in yolo mode, interactive mode, and (hypothetically) a fully sandboxed mode — the security policy is outside the core loop.

**Undo is stack-based.** Each `write_file` and `edit_file` pushes the previous content onto a per-file stack. `/undo` pops one entry at a time, so repeated calls walk back through the full history.

---

## 4. Known gaps — for discussion

### 4.1 No context window guard

**The problem:** `self.history` grows without bound. If a long session approaches the model's context window, the API returns a 400 error. There is no automatic safeguard.

**Why it matters:** The `/compact` command exists but requires the user to know to run it. In a long autonomous run, the agent will eventually crash mid-task.

**Options to discuss:**
- Auto-compact when estimated token count crosses a threshold (e.g. 80% of the model's context window)
- Rolling window: drop the oldest messages, keeping the first system-like message and the last N turns
- Hierarchical memory: summarise old turns into a persistent "working memory" block injected into the system prompt
- **Context reset (vs. compaction):** Anthropic's own long-running agent work found that *resetting* — clearing history and handing off a structured summary to a fresh session — outperformed in-place compaction. Compaction keeps the same context growing; it can still produce "context anxiety" where the model senses it's near a limit and prematurely wraps up work. A reset gives a clean slate. The trade-off is that structured handoff prompts require careful design so nothing load-bearing is lost.

### 4.2 Tools execute serially

**The problem:** When the model returns multiple `tool_use` blocks in a single response, they are executed one by one in a `for` loop. If the model calls `read_file` on three files simultaneously, we wait for each in sequence.

**Why it matters:** On tasks that involve reading many files or running multiple checks, serial execution is meaningfully slower.

**Options to discuss:**
- `asyncio` + `ThreadPoolExecutor` for I/O-bound tools
- Keep bash serial (side effects make parallel execution unsafe) but parallelize read-only tools
- Annotate tools as `side_effect_free` in their schema and parallelize those automatically

### 4.3 Task state is a module-level global

**The problem:** `_TASKS` in `tools.py` is a module-level list. It is not reset with `/reset`, persists across agent instances in the same process, and would be shared across threads.

**Why it matters:** In evaluation runs where many agents are spawned programmatically, or in any multi-session setup, tasks from one run bleed into the next.

**Fix:** Move task state into the `Agent` instance and pass a reference into the `dispatch` function. Small change, high-value.

### 4.4 No retry / resilience on API errors

**The problem:** If the Anthropic API returns a transient 529 (overloaded) or network timeout, the exception bubbles up and kills the turn.

**Why it matters:** Long autonomous runs are fragile. A single transient error discards all in-progress work.

**Options to discuss:**
- Exponential backoff with jitter on 429/529 responses
- Checkpoint the history to disk so a run can be resumed after a crash
- The trace file already logs everything — could be replayed if we add a replay mode

### 4.5 No tool output size management

**The problem:** `bash` truncates at 8 KB and `read_file` at 200 lines, but there is no global budget. A `grep` on a large codebase can return thousands of lines. All of it goes into the context.

**Why it matters:** Large tool results accelerate context exhaustion and increase cost per turn.

**Options to discuss:**
- Per-tool output limits (already partially done for bash and read_file — make it consistent)
- "Summarise this result" post-processing for oversized outputs
- Pagination tokens so the model can ask for the next page of results

### 4.6 No structured diff / patch tool

**The problem:** `edit_file` does string replacement. For multi-location edits — adding an import, changing a function signature, updating a call site — the model must make separate calls for each location. It cannot express "apply this unified diff."

**Why it matters:** Refactors that touch many locations in one file require many round-trips, and each replacement must be unique enough to identify the location, which is fragile.

**Options to discuss:**
- Add a `patch_file` tool that accepts a unified diff string
- Add a `multi_edit_file` tool that takes a list of `{old, new}` pairs and applies them atomically
- Both can still use the same undo stack

### 4.7 The agent cannot reliably evaluate its own work

**The problem:** When the model is asked to review or score something it just produced, it tends to confidently approve its own output — even when the quality is obviously poor to a human observer. This is not a prompting problem; it is a structural one. The generator and the evaluator share the same context and the same priors.

**Why it matters:** The current harness has no independent quality gate. If the model writes broken code and then checks it, it will often rationalise the breakage or miss it entirely. Tasks that require objective quality assessment — "did the tests pass?", "does this actually work?" — need a verification step that is structurally separated from generation.

**Options to discuss:**
- **Separate evaluator agent**: spawn a second `Agent` instance with a fresh context whose only job is to test and score the output of the first. This is the GAN-inspired pattern — see section 6 for the fuller architecture.
- **External verification tools**: for coding tasks, "did it work?" is often answerable by the tools themselves (`bash` running `pytest`, a type-checker, a linter). The key is that the verification result is treated as ground truth, not handed back to the same model for interpretation.
- **Pre-negotiated success criteria**: define what "done" means *before* generation starts. The evaluator checks against that spec, not against the generator's own assessment of its work.

### 4.8 Security model for bash

**The problem:** `shell=True` in `subprocess.run` means a crafted file path or injected string in a tool argument can escape into the shell. The approval gate mitigates this in interactive mode, but in yolo mode there is no guard.

**Why it matters:** Prompt injection through file content is a real attack vector when the agent reads files from untrusted sources.

**Options to discuss:**
- Prefer `shell=False` with `shlex.split` for structured commands
- Sandbox via Docker or a restricted environment for untrusted repos
- Read-only mode: disable bash and write tools entirely, useful for "explain this codebase" use cases

---

## 5. Engineering principles worth keeping

**1. Keep the loop dumb.** The agentic loop itself should have no domain knowledge. It calls the model, executes tools, repeats. All intelligence lives in the model and the tools. Resist the temptation to add heuristics inside the loop.

**2. Tools should be idempotent where possible.** `write_file` on the same content twice should not be a problem. `read_file` is inherently idempotent. `bash` is the only tool that is not — which is why it has a special approval gate.

**3. Every tool result is context.** Tool outputs go directly into the model's context window. Verbose outputs are not just slower — they crowd out the information the model actually needs. Truncation limits are a feature, not a compromise.

**4. The trace file is the ground truth.** Token counts in the UI are estimates. Cost per turn is derived from those estimates. The JSONL trace is exact and can be used to reconstruct any session — treat it as the audit log, not the console output.

**5. The plugin system is the extension point.** Adding capability to the agent means adding a tool, not modifying the loop. A new tool should be a single file in `plugins/`. If adding capability requires touching `agent.py`, that is a design smell.

**6. Approval mode is a spectrum, not a binary.** The current design has `yolo` (all commands auto-approved) vs. interactive (all commands ask). A more useful model is per-category: auto-approve reads, ask for writes, always ask for network commands. This is worth building before any production or shared use.

**7. Every harness component encodes an assumption about what the model can't do alone.** Before adding complexity — a multi-agent loop, an evaluator, sprint decomposition — ask: what specific failure mode does this address? If you can't name it, the component is probably overhead. And when the model improves, re-examine. Components that were load-bearing on an older model may be pure cost on a newer one. The right harness for claude-sonnet-4-6 is not the same as the right harness for claude-opus-4-6.

**8. Start with the simplest harness that could work, then add complexity only where you can measure the lift.** Anthropic's own production work found that simplifying the harness — removing sprint decomposition that was necessary on earlier models — improved results on newer ones. Complexity that isn't load-bearing isn't neutral; it adds latency, cost, and failure surface. The discipline is methodical removal testing: cut a component, measure on real tasks, keep the cut if quality holds.

---

## 6. Potential directions — open questions for the meeting

- **Evaluation harness**: How do we test that the agent actually solves tasks correctly, not just that it runs without errors? We have the trace file — can we build a replay-and-score loop around it?

- **Headless / scripted mode**: The `Agent.run()` method already exists for non-streaming callers. How far are we from running this in CI — e.g. "fix the failing tests on this branch"?

- **Generator-evaluator (GAN-inspired) architecture**: The most actionable multi-agent pattern from Anthropic's production work is not general collaboration but a specific two-role loop: one agent generates, a separate agent evaluates against explicit criteria and returns structured feedback, and the loop runs 5–15 cycles. The evaluator's prompt needs careful tuning — out of the box, models identify problems and then rationalise approving flawed work anyway. Getting a genuinely skeptical evaluator requires iterative prompt work on realistic tasks, reading traces to find where it let things through. Worth discussing: what would the grading criteria look like for our specific use cases?

- **Sprint contracts**: For long or complex tasks, pre-negotiating success criteria before implementation begins proved load-bearing in Anthropic's work. The pattern: before a task starts, the planner and evaluator agree on a specific, testable list of what "done" means. This bridges the gap between a high-level prompt and a verifiable outcome. In our context, this could be as simple as a structured preamble the user writes before a complex one-shot run.

- **Persistent memory across sessions**: Right now, every session starts cold. Should the agent be able to recall project-specific conventions, past decisions, known gotchas? This is a separate problem from context compaction — it's about long-horizon continuity.

- **Cost controls**: There are no hard limits on tokens per session or per turn. In a team setting, who controls the budget, and how? Anthropic's production runs reached $200 for a single complex task. That's fine when it's intentional; it's a problem when it isn't.

---

## 7. File map

```
agent.py           — Agentic loop, streaming, token tracking, history compaction
tools.py           — Built-in tool implementations, dispatch, schemas
tool_registry.py   — @tool decorator, schema auto-generation, plugin loader
cli.py             — Argument parsing, REPL, one-shot runner
repl_dispatch.py   — Slash-command handling (shared by REPL and TUI)
tui.py             — Full-screen Textual UI
plugins/           — Custom tool files (auto-loaded at startup)
  example_tools.py   — word_count, tree, env_var
  web_search.py      — Tavily + SerpAPI search tools
```
