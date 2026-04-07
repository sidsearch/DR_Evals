# coding-agent

A terminal coding agent built on the Anthropic API. Streams responses, executes tools, tracks tasks, and is designed to be extended with custom tools.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
```

## Usage

**Interactive REPL:**
```bash
python cli.py
python cli.py --dir /path/to/project
python cli.py --model claude-sonnet-4-6
```

**One-shot:**
```bash
python cli.py "add type annotations to utils.py"
```

**Flags:**

| Flag | Description |
|------|-------------|
| `--model MODEL` | Claude model ID (default: `claude-opus-4-6`) |
| `--dir DIR` | Working directory (default: `.`) |
| `--max-tokens N` | Max output tokens (default: 8096) |
| `--yolo` | Auto-approve all bash commands without prompting |
| `--trace FILE` | Log every tool call to a JSONL file (e.g. `trace.jsonl`) |

## REPL commands

| Command | Description |
|---------|-------------|
| `/tools` | List all available tools (built-in and plugins) |
| `/tasks` | Show the agent's current task list |
| `/compact` | Summarize conversation history to free context space |
| `/cost` | Show session token usage and estimated cost |
| `/model <id>` | Switch model mid-session |
| `/yolo` | Toggle bash approval mode on/off |
| `/undo <path>` | Revert a file to its state before the last agent edit |
| `/save [file]` | Save conversation history to JSON (default: `history.json`) |
| `/load [file]` | Load conversation history from JSON |
| `/reload` | Hot-reload plugins from the `plugins/` directory |
| `/history` | Show number of turns in history |
| `/reset` | Clear history and token counts |
| `/quit` | Exit |

## Built-in tools

The agent has access to these tools out of the box:

| Tool | Description |
|------|-------------|
| `read_file` | Read lines from a file with offset/limit paging |
| `write_file` | Write (or overwrite) a file; previous content saved for undo |
| `edit_file` | Replace the first occurrence of a string in a file |
| `undo_edit` | Revert a file to its state before the last write or edit |
| `bash` | Run a shell command (subject to approval mode) |
| `find_files` | Find files matching a glob pattern |
| `grep` | Search files with a regex pattern |
| `ls` | List files and directories |
| `task_create` | Create a task to track a step in complex work |
| `task_update` | Update a task's status (`pending`, `in_progress`, `done`, `blocked`) |
| `task_list` | List all tasks and their status |

## Adding custom tools

Drop a `.py` file into the `plugins/` directory. Any function decorated with `@tool` is automatically registered and available to the agent on next startup (or after `/reload`).

```python
# plugins/my_tools.py
from tool_registry import tool

@tool
def fetch_url(url: str) -> str:
    """Fetch the text content of a URL (first 4000 chars).

    Args:
        url: The URL to fetch.
    """
    import urllib.request
    with urllib.request.urlopen(url) as r:
        return r.read().decode(errors="replace")[:4000]
```

The `@tool` decorator builds the JSON schema automatically from:
- **Type hints** → JSON type (`str`→`string`, `int`→`integer`, `float`→`number`, `bool`→`boolean`)
- **Docstring first line** → tool description
- **Google-style `Args:` block** → parameter descriptions
- **Parameters without defaults** → marked as required

You can also override the name or description explicitly:

```python
@tool(name="run_sql", description="Execute a read-only SQL query and return results.")
def run_sql(query: str, database: str = "main.db") -> str:
    ...
```

See `plugins/example_tools.py` for more examples (`word_count`, `tree`, `env_var`).

### Web search

`plugins/web_search.py` is included out of the box. Enable it by setting one or both keys:

```bash
export TAVILY_API_KEY=tvly-...       # https://app.tavily.com
export SERPAPI_API_KEY=...           # https://serpapi.com
```

This registers three tools:

| Tool | Description |
|------|-------------|
| `web_search` | Auto-picks Tavily if available, falls back to SerpAPI |
| `tavily_search` | Tavily directly — supports `basic`/`advanced` search depth |
| `serp_search` | SerpAPI directly — supports `google`, `bing`, `duckduckgo`, etc. |

## Task tracking

For complex requests, the agent automatically breaks work into subtasks using `task_create` / `task_update`. Use `/tasks` to see current progress:

```
◐ #1 [in_progress] Read existing test suite
● #2 [done] Add unit tests for auth module
○ #3 [pending] Run tests and fix failures
```

## Tracing

Use `--trace trace.jsonl` to log every tool call for debugging or evaluation:

```bash
python cli.py --trace trace.jsonl "refactor the data pipeline"
```

Each line in the file is a JSON object:
```json
{"ts": "2026-04-06T10:00:00Z", "event": "tool_call", "tool": "bash", "inputs": {"command": "pytest"}, "result_preview": "..."}
```

## Project structure

```
cli.py            — REPL and one-shot entry point
agent.py          — Agentic loop, streaming, token tracking, history compaction
tools.py          — Built-in tool implementations and dispatch
tool_registry.py  — @tool decorator and plugin auto-loader
plugins/          — Drop custom tool files here
  example_tools.py  — Example: word_count, tree, env_var
```
