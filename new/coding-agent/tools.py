"""
Tool implementations for the coding agent.
Each tool is a plain function + a JSON schema describing it to the LLM.
"""

import subprocess
import glob as glob_module
import os
from pathlib import Path
from typing import Any, Callable

# Tracks previous content of files before each edit/write,
# keyed by absolute path. Each entry is a stack (newest last).
_EDIT_HISTORY: dict[str, list[str]] = {}


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def read_file(path: str, offset: int = 1, limit: int = 200) -> str:
    """Read lines [offset, offset+limit) from a file (1-indexed)."""
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
        total = len(lines)
        start = max(0, offset - 1)
        end = min(total, start + limit)
        chunk = lines[start:end]
        header = f"[{path}  lines {start+1}-{end} of {total}]\n"
        return header + "\n".join(f"{start+i+1:4}  {l}" for i, l in enumerate(chunk))
    except FileNotFoundError:
        return f"ERROR: file not found: {path}"
    except Exception as e:
        return f"ERROR: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent dirs as needed."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Save previous content for undo
        if p.exists():
            key = str(p.resolve())
            _EDIT_HISTORY.setdefault(key, []).append(p.read_text(errors="replace"))
        p.write_text(content)
        lines = content.count("\n") + 1
        return f"OK: wrote {lines} lines to {path}"
    except Exception as e:
        return f"ERROR: {e}"


def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Replace old_string with new_string in a file.
    By default replaces only the first occurrence; set replace_all=True to replace every occurrence.
    """
    try:
        p = Path(path)
        text = p.read_text()
        if old_string not in text:
            return f"ERROR: old_string not found in {path}"
        # Save previous content for undo
        _EDIT_HISTORY.setdefault(str(p.resolve()), []).append(text)
        count = text.count(old_string)
        updated = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
        p.write_text(updated)
        replaced = count if replace_all else 1
        return f"OK: edited {path} ({replaced} replacement{'s' if replaced != 1 else ''})"
    except FileNotFoundError:
        return f"ERROR: file not found: {path}"
    except Exception as e:
        return f"ERROR: {e}"


def undo_edit(path: str) -> str:
    """Revert a file to its state before the last write_file or edit_file call.
    Can be called multiple times to step back through the full edit history.
    """
    key = str(Path(path).resolve())
    stack = _EDIT_HISTORY.get(key)
    if not stack:
        return f"ERROR: no edit history for {path}"
    previous = stack.pop()
    if not stack:
        del _EDIT_HISTORY[key]
    Path(path).write_text(previous)
    lines = previous.count("\n") + 1
    remaining = len(stack)
    extra = f"  ({remaining} older snapshot{'s' if remaining != 1 else ''} available)" if remaining else ""
    return f"OK: reverted {path} to previous state ({lines} lines){extra}"


def bash(command: str, timeout: int = 30) -> str:
    """Run a shell command and return stdout + stderr (truncated to 8 KB)."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += result.stderr
        if result.returncode != 0:
            output += f"\n[exit code {result.returncode}]"
        output = output or "(no output)"
        limit = 8192
        if len(output) > limit:
            output = output[:limit] + f"\n... [truncated, {len(output)} total chars]"
        return output
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


def find_files(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern under path."""
    try:
        base = Path(path).resolve()
        matches = sorted(glob_module.glob(str(base / "**" / pattern), recursive=True))
        if not matches:
            return f"No files found matching '{pattern}' under {path}"
        rel = [os.path.relpath(m) for m in matches[:200]]
        result = "\n".join(rel)
        if len(matches) > 200:
            result += f"\n... and {len(matches)-200} more"
        return result
    except Exception as e:
        return f"ERROR: {e}"


def grep(pattern: str, path: str = ".", file_glob: str = "*") -> str:
    """Search for a regex pattern in files matching file_glob under path."""
    try:
        cmd = ["grep", "-rn", "--include", file_glob, "-E", pattern, path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout or "(no matches)"
        if len(output) > 8192:
            output = output[:8192] + "\n... [truncated]"
        return output
    except Exception as e:
        return f"ERROR: {e}"


def ls(path: str = ".") -> str:
    """List files and directories at path."""
    try:
        p = Path(path)
        if not p.exists():
            return f"ERROR: path not found: {path}"
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
        lines = []
        for e in entries:
            if e.is_dir():
                lines.append(f"  {e.name}/")
            else:
                size = e.stat().st_size
                lines.append(f"  {e.name}  ({size:,} bytes)")
        return f"[{path}]\n" + "\n".join(lines) if lines else f"[{path}] (empty)"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Task tracking  (inspired by LangChain deep agents)
# ---------------------------------------------------------------------------

_TASKS: list[dict] = []
_TASK_STATUSES = {"pending", "in_progress", "done", "blocked"}


def task_create(description: str) -> str:
    """Create a new task with status 'pending' and return its ID."""
    task_id = len(_TASKS) + 1
    _TASKS.append({"id": task_id, "description": description, "status": "pending", "notes": ""})
    return f"OK: created task #{task_id} — {description}"


def task_update(task_id: int, status: str, notes: str = "") -> str:
    """Update the status (and optional notes) of a task.
    Valid statuses: pending, in_progress, done, blocked.
    """
    if status not in _TASK_STATUSES:
        return f"ERROR: invalid status '{status}'. Use: {', '.join(sorted(_TASK_STATUSES))}"
    for t in _TASKS:
        if t["id"] == task_id:
            t["status"] = status
            if notes:
                t["notes"] = notes
            return f"OK: task #{task_id} → {status}"
    return f"ERROR: task #{task_id} not found"


def task_list() -> str:
    """List all tasks with their current status."""
    if not _TASKS:
        return "(no tasks)"
    icons = {"pending": "○", "in_progress": "◐", "done": "●", "blocked": "✗"}
    lines = []
    for t in _TASKS:
        icon = icons.get(t["status"], "?")
        line = f"{icon} #{t['id']} [{t['status']}] {t['description']}"
        if t["notes"]:
            line += f"\n    → {t['notes']}"
        lines.append(line)
    return "\n".join(lines)


def tasks_snapshot() -> list[dict]:
    """Return a copy of the tasks list (for the CLI task display)."""
    return list(_TASKS)


# ---------------------------------------------------------------------------
# Dispatch table  {name -> (fn, schema)}
# ---------------------------------------------------------------------------

TOOLS: dict[str, tuple[Any, dict]] = {
    "read_file": (
        read_file,
        {
            "name": "read_file",
            "description": "Read lines from a file. Use offset/limit to page through large files.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":   {"type": "string", "description": "File path to read"},
                    "offset": {"type": "integer", "description": "First line to read (1-indexed, default 1)"},
                    "limit":  {"type": "integer", "description": "Max lines to return (default 200)"},
                },
                "required": ["path"],
            },
        },
    ),
    "write_file": (
        write_file,
        {
            "name": "write_file",
            "description": "Write content to a file (creates or overwrites). Parent dirs are created automatically. Previous content is saved for undo.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":    {"type": "string", "description": "Destination file path"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    ),
    "edit_file": (
        edit_file,
        {
            "name": "edit_file",
            "description": "Replace old_string with new_string in a file. Replaces only the first occurrence unless replace_all=true. Previous content is saved for undo.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":        {"type": "string",  "description": "File to edit"},
                    "old_string":  {"type": "string",  "description": "Exact text to find and replace"},
                    "new_string":  {"type": "string",  "description": "Text to replace it with"},
                    "replace_all": {"type": "boolean", "description": "If true, replace every occurrence (default false)"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    ),
    "undo_edit": (
        undo_edit,
        {
            "name": "undo_edit",
            "description": "Revert a file one step back through its edit history. Can be called repeatedly to undo multiple edits.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to revert"},
                },
                "required": ["path"],
            },
        },
    ),
    "bash": (
        bash,
        {
            "name": "bash",
            "description": "Execute a shell command. Returns stdout + stderr. Avoid interactive commands.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
                },
                "required": ["command"],
            },
        },
    ),
    "find_files": (
        find_files,
        {
            "name": "find_files",
            "description": "Find files matching a glob pattern (e.g. '*.py') under a directory.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.py' or 'test_*.py'"},
                    "path":    {"type": "string", "description": "Root directory to search (default '.')"},
                },
                "required": ["pattern"],
            },
        },
    ),
    "grep": (
        grep,
        {
            "name": "grep",
            "description": "Search for a regex pattern across files. Returns file:line:match lines.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern":   {"type": "string", "description": "Regex pattern to search for"},
                    "path":      {"type": "string", "description": "Directory to search in (default '.')"},
                    "file_glob": {"type": "string", "description": "Filter files by glob, e.g. '*.py' (default '*')"},
                },
                "required": ["pattern"],
            },
        },
    ),
    "ls": (
        ls,
        {
            "name": "ls",
            "description": "List files and subdirectories at a path.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory to list (default '.')"},
                },
                "required": [],
            },
        },
    ),
    "task_create": (
        task_create,
        {
            "name": "task_create",
            "description": "Create a new task to track a step in the current work. Use this to break complex requests into discrete subtasks.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Short description of what this task involves"},
                },
                "required": ["description"],
            },
        },
    ),
    "task_update": (
        task_update,
        {
            "name": "task_update",
            "description": "Update a task's status. Call with in_progress when starting, done when finished, blocked if stuck.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "Task ID returned by task_create"},
                    "status":  {"type": "string", "description": "New status: pending | in_progress | done | blocked"},
                    "notes":   {"type": "string", "description": "Optional notes about progress or blockers"},
                },
                "required": ["task_id", "status"],
            },
        },
    ),
    "task_list": (
        task_list,
        {
            "name": "task_list",
            "description": "List all tasks and their current status.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    ),
}


def _merge_plugins() -> None:
    """Load tools registered via @tool (from plugins and direct registry use)."""
    try:
        from tool_registry import load_plugins, registry_tools
        loaded = load_plugins("plugins")
        if loaded:
            pass  # modules are loaded; registry is populated as a side effect
        for name, entry in registry_tools().items():
            if name not in TOOLS:
                TOOLS[name] = entry
    except ImportError:
        pass


# Merge plugin tools into TOOLS at import time
_merge_plugins()


def dispatch(name: str, inputs: dict, approval_fn: Callable[[str], bool] | None = None) -> str:
    """Call a tool by name with the given inputs dict.

    For the 'bash' tool, approval_fn (if provided) is called with the command
    string. If it returns False the command is not run.
    """
    if name not in TOOLS:
        return f"ERROR: unknown tool '{name}'"
    fn, _ = TOOLS[name]
    # Bash approval gate
    if name == "bash" and approval_fn is not None:
        command = inputs.get("command", "")
        if not approval_fn(command):
            return "ERROR: command rejected by user"
    try:
        return fn(**inputs)
    except TypeError as e:
        return f"ERROR: bad arguments for tool '{name}': {e}"


def schemas() -> list[dict]:
    """Return just the schemas (for passing to the Anthropic API)."""
    return [schema for _, schema in TOOLS.values()]


def edit_history_keys() -> list[str]:
    """Return the paths that currently have undo history."""
    return list(_EDIT_HISTORY.keys())
