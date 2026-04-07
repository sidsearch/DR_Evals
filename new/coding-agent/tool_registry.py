"""
Tool registry — decorator-based tool registration with automatic JSON schema
generation from type hints and Google-style docstrings.

Quick start
-----------
1. Create a .py file in the plugins/ directory.
2. Import @tool and decorate your functions.
3. The agent auto-loads all plugins at startup.

Example plugin (plugins/my_tools.py):

    from tool_registry import tool

    @tool
    def word_count(path: str) -> str:
        \"\"\"Count words in a file.

        Args:
            path: Path to the file.
        \"\"\"
        from pathlib import Path
        try:
            text = Path(path).read_text(errors="replace")
            return f"{len(text.split())} words in {path}"
        except FileNotFoundError:
            return f"ERROR: file not found: {path}"

That's it. The tool is now available to the agent.
"""

import importlib.util
import inspect
from pathlib import Path
from typing import Any, Callable

# {tool_name: (function, schema_dict)}
_REGISTRY: dict[str, tuple[Callable, dict]] = {}

_TYPE_MAP: dict[Any, str] = {
    str:   "string",
    int:   "integer",
    float: "number",
    bool:  "boolean",
    list:  "array",
    dict:  "object",
}


def _parse_docstring(fn: Callable) -> tuple[str, dict[str, str]]:
    """Return (summary_line, {param_name: description}) from a Google-style docstring."""
    doc = inspect.getdoc(fn) or ""
    lines = doc.split("\n")
    summary = lines[0].strip() if lines else ""
    param_docs: dict[str, str] = {}
    in_args = False
    for line in lines[1:]:
        stripped = line.strip()
        low = stripped.lower()
        if low in ("args:", "arguments:", "parameters:"):
            in_args = True
            continue
        if in_args:
            if stripped and not line.startswith((" ", "\t")):
                in_args = False
                continue
            if ":" in stripped:
                pname, _, pdesc = stripped.partition(":")
                param_docs[pname.strip()] = pdesc.strip()
    return summary, param_docs


def _build_schema(fn: Callable, tool_name: str, tool_desc: str) -> dict:
    """Build an Anthropic tool schema dict from a function's signature."""
    sig = inspect.signature(fn)
    _, param_docs = _parse_docstring(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        ann = param.annotation
        if ann is inspect.Parameter.empty:
            json_type = "string"
        else:
            json_type = _TYPE_MAP.get(ann, "string")

        prop: dict[str, Any] = {"type": json_type}
        if param_name in param_docs:
            prop["description"] = param_docs[param_name]

        properties[param_name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "name": tool_name,
        "description": tool_desc,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def tool(fn: Callable | None = None, *, name: str | None = None, description: str | None = None):
    """
    Decorator that registers a function as an agent tool.

    Can be used with or without arguments:

        @tool
        def my_tool(x: str) -> str: ...

        @tool(name="custom", description="Override desc")
        def my_tool(x: str) -> str: ...
    """
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        doc_summary, _ = _parse_docstring(func)
        tool_desc = description or doc_summary or func.__name__
        schema = _build_schema(func, tool_name, tool_desc)
        _REGISTRY[tool_name] = (func, schema)
        return func

    if fn is not None:
        return decorator(fn)
    return decorator


def load_plugins(plugins_dir: str = "plugins") -> list[str]:
    """
    Import every non-underscore .py file in plugins_dir.
    Any function decorated with @tool is registered automatically.
    Returns the list of module names that were loaded.
    """
    loaded: list[str] = []
    p = Path(plugins_dir)
    if not p.is_dir():
        return loaded
    for py_file in sorted(p.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                loaded.append(py_file.stem)
            except Exception as exc:
                print(f"[tool_registry] WARNING: failed to load {py_file}: {exc}")
    return loaded


def registry_tools() -> dict[str, tuple[Any, dict]]:
    """Return a copy of the current registry."""
    return dict(_REGISTRY)
