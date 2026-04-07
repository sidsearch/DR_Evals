"""
Example custom tools — copy this file or add more tools here.
Any function decorated with @tool is automatically available to the agent.

To add your own tool:
  1. Write a Python function that returns a string.
  2. Decorate it with @tool.
  3. Use type annotations and a Google-style docstring for best results.
  4. The agent will pick it up on next startup (or after /reload).

Type hint → JSON schema mapping:
  str   → "string"
  int   → "integer"
  float → "number"
  bool  → "boolean"
  list  → "array"
  dict  → "object"
"""

import os
from pathlib import Path

# tool_registry is one directory up — adjust the import path at runtime
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from tool_registry import tool


@tool
def word_count(path: str) -> str:
    """Count words and lines in a file.

    Args:
        path: Path to the file.
    """
    try:
        text = Path(path).read_text(errors="replace")
        words = len(text.split())
        lines = text.count("\n") + 1
        return f"{path}: {lines} lines, {words} words"
    except FileNotFoundError:
        return f"ERROR: file not found: {path}"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def tree(path: str = ".", max_depth: int = 3) -> str:
    """Show a directory tree up to max_depth levels deep.

    Args:
        path: Root directory to display.
        max_depth: Maximum depth to recurse (default 3).
    """
    def _walk(p: Path, depth: int, prefix: str) -> list[str]:
        if depth > max_depth:
            return []
        try:
            entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
        except PermissionError:
            return [prefix + "  [permission denied]"]
        lines = []
        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(prefix + connector + entry.name + ("/" if entry.is_dir() else ""))
            if entry.is_dir():
                extension = "    " if i == len(entries) - 1 else "│   "
                lines.extend(_walk(entry, depth + 1, prefix + extension))
        return lines

    root = Path(path).resolve()
    if not root.exists():
        return f"ERROR: path not found: {path}"
    result = [str(root)]
    result.extend(_walk(root, 1, ""))
    return "\n".join(result)


@tool
def env_var(name: str) -> str:
    """Read an environment variable (returns empty string if not set).

    Args:
        name: Environment variable name (e.g. DATABASE_URL).
    """
    val = os.environ.get(name)
    if val is None:
        return f"(not set)"
    # Mask anything that looks like a secret
    lower = name.lower()
    if any(k in lower for k in ("key", "secret", "token", "password", "pass", "pwd")):
        return f"{name}=***REDACTED***"
    return f"{name}={val}"
