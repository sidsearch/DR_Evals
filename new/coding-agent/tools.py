"""
Tool implementations for the coding agent.
Each tool is a plain function + a JSON schema describing it to the LLM.
"""

import subprocess
import glob as glob_module
import os
from pathlib import Path
from typing import Any


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
        p.write_text(content)
        lines = content.count("\n") + 1
        return f"OK: wrote {lines} lines to {path}"
    except Exception as e:
        return f"ERROR: {e}"


def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Replace the first occurrence of old_string with new_string in a file."""
    try:
        text = Path(path).read_text()
        if old_string not in text:
            return f"ERROR: old_string not found in {path}"
        updated = text.replace(old_string, new_string, 1)
        Path(path).write_text(updated)
        return f"OK: edited {path}"
    except FileNotFoundError:
        return f"ERROR: file not found: {path}"
    except Exception as e:
        return f"ERROR: {e}"


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
            "description": "Write content to a file (creates or overwrites). Parent dirs are created automatically.",
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
            "description": "Replace the first occurrence of old_string with new_string in a file. old_string must be unique enough to identify the exact location.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path":       {"type": "string", "description": "File to edit"},
                    "old_string": {"type": "string", "description": "Exact text to find and replace"},
                    "new_string": {"type": "string", "description": "Text to replace it with"},
                },
                "required": ["path", "old_string", "new_string"],
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
}


def dispatch(name: str, inputs: dict) -> str:
    """Call a tool by name with the given inputs dict."""
    if name not in TOOLS:
        return f"ERROR: unknown tool '{name}'"
    fn, _ = TOOLS[name]
    try:
        return fn(**inputs)
    except TypeError as e:
        return f"ERROR: bad arguments for tool '{name}': {e}"


def schemas() -> list[dict]:
    """Return just the schemas (for passing to the Anthropic API)."""
    return [schema for _, schema in TOOLS.values()]
