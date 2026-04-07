"""
Shared REPL slash-command handling for console and TUI modes.
Returns actions and lines to print (markup or plain).
"""

from __future__ import annotations

import json
from enum import StrEnum
from io import StringIO
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from tools import edit_history_keys, tasks_snapshot, undo_edit, TOOLS

if TYPE_CHECKING:
    from agent import Agent

# Pricing (USD per million tokens) — update as needed
COST_PER_M: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.25, 1.25),
    "claude-haiku-4-5-20251001": (0.25, 1.25),
}
DEFAULT_COST = (15.0, 75.0)


def cost_for(model: str, input_tok: int, output_tok: int) -> float:
    rates = COST_PER_M.get(model, DEFAULT_COST)
    return input_tok / 1e6 * rates[0] + output_tok / 1e6 * rates[1]


def format_turn_cost_line(agent: "Agent") -> str:
    turn_cost = cost_for(agent.model, agent.turn_input_tokens, agent.turn_output_tokens)
    total_cost = cost_for(agent.model, agent.total_input_tokens, agent.total_output_tokens)
    return (
        f"[dim]  tokens ↑{agent.turn_input_tokens:,} ↓{agent.turn_output_tokens:,}"
        f"  turn ${turn_cost:.4f}  session ${total_cost:.4f}[/dim]"
    )


class ReplAction(StrEnum):
    QUIT = "quit"
    CONTINUE = "continue"
    AGENT = "agent"


# (text, use_markup)
ReplLine = tuple[str, bool]

_BUILTIN_TOOLS = frozenset([
    "read_file", "write_file", "edit_file", "undo_edit",
    "bash", "find_files", "grep", "ls",
    "task_create", "task_update", "task_list",
])


def _table_lines(table: Table, width: int = 88) -> list[ReplLine]:
    buf = StringIO()
    Console(file=buf, width=width).print(table)
    text = buf.getvalue().rstrip("\n")
    return [(text, False)] if text else []


def repl_dispatch(
    user_input: str,
    agent: "Agent",
    yolo_flag: list[bool],
) -> tuple[ReplAction, list[ReplLine]]:
    """
    Handle one REPL line. Returns (action, lines) where lines are (text, markup).
    """
    lines: list[ReplLine] = []

    if user_input == "/quit":
        lines.append(("[dim]bye.[/dim]", True))
        return (ReplAction.QUIT, lines)

    if user_input == "/reset":
        agent.reset()
        lines.append(("[yellow]history and token counts cleared.[/yellow]", True))
        return (ReplAction.CONTINUE, lines)

    if user_input == "/history":
        turns = sum(1 for m in agent.history if m["role"] == "user")
        lines.append((f"[dim]{turns} user turn(s) in history.[/dim]", True))
        return (ReplAction.CONTINUE, lines)

    if user_input == "/cost":
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="dim")
        table.add_column(style="white")
        table.add_row("model", agent.model)
        table.add_row("input tokens", f"{agent.total_input_tokens:,}")
        table.add_row("output tokens", f"{agent.total_output_tokens:,}")
        rates = COST_PER_M.get(agent.model, DEFAULT_COST)
        table.add_row("input rate", f"${rates[0]:.2f}/M")
        table.add_row("output rate", f"${rates[1]:.2f}/M")
        total = cost_for(agent.model, agent.total_input_tokens, agent.total_output_tokens)
        table.add_row("total cost", f"[bold]${total:.4f}[/bold]")
        lines.extend(_table_lines(table))
        return (ReplAction.CONTINUE, lines)

    if user_input == "/tools":
        lines.append(("[bold]available tools:[/bold]", True))
        for name, (_, schema) in TOOLS.items():
            desc = schema.get("description", "")[:70]
            tag = "[dim](plugin)[/dim]" if name not in _BUILTIN_TOOLS else ""
            lines.append((f"  [cyan]{name}[/cyan]  {desc} {tag}", True))
        return (ReplAction.CONTINUE, lines)

    if user_input == "/tasks":
        tasks = tasks_snapshot()
        if not tasks:
            lines.append(("[dim]no tasks.[/dim]", True))
        else:
            icons = {"pending": "○", "in_progress": "◐", "done": "●", "blocked": "✗"}
            for t in tasks:
                icon = icons.get(t["status"], "?")
                color = {"pending": "dim", "in_progress": "yellow", "done": "green", "blocked": "red"}.get(
                    t["status"], "white"
                )
                lines.append(
                    (
                        f"  [{color}]{icon} #{t['id']} [{t['status']}] {t['description']}[/{color}]",
                        True,
                    )
                )
                if t["notes"]:
                    lines.append((f"    [dim]→ {t['notes']}[/dim]", True))
        return (ReplAction.CONTINUE, lines)

    if user_input == "/compact":
        lines.append(("[yellow]compacting history…[/yellow]", True))
        try:
            summary = agent.compact_history()
            buf = StringIO()
            c = Console(file=buf, width=88)
            c.print(Rule(style="dim"))
            c.print("[bold]summary:[/bold]")
            c.print(summary, markup=False)
            c.print(Rule(style="dim"))
            lines.append((buf.getvalue().rstrip("\n"), False))
            lines.append(("[green]history compacted to 2 messages.[/green]", True))
        except Exception as e:
            lines.append((f"[red]compact failed: {e}[/red]", True))
        return (ReplAction.CONTINUE, lines)

    if user_input == "/reload":
        try:
            from tool_registry import load_plugins, registry_tools

            loaded = load_plugins("plugins")
            for name, entry in registry_tools().items():
                if name not in TOOLS:
                    TOOLS[name] = entry
            if loaded:
                lines.append((f"[green]reloaded plugins: {', '.join(loaded)}[/green]", True))
            else:
                lines.append(("[dim]no plugins found in plugins/[/dim]", True))
        except Exception as e:
            lines.append((f"[red]reload failed: {e}[/red]", True))
        return (ReplAction.CONTINUE, lines)

    if user_input == "/yolo":
        yolo_flag[0] = not yolo_flag[0]
        state = "ON (auto-approve)" if yolo_flag[0] else "OFF (ask before each command)"
        lines.append((f"[yellow]bash approval: {state}[/yellow]", True))
        return (ReplAction.CONTINUE, lines)

    if user_input.startswith("/model"):
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            lines.append((f"[dim]current model: {agent.model}[/dim]", True))
            lines.append(("[dim]usage: /model <model-id>[/dim]", True))
        else:
            agent.model = parts[1].strip()
            lines.append((f"[yellow]switched to model: {agent.model}[/yellow]", True))
        return (ReplAction.CONTINUE, lines)

    if user_input.startswith("/save"):
        parts = user_input.split(maxsplit=1)
        path = parts[1].strip() if len(parts) > 1 else "history.json"
        try:
            with open(path, "w") as f:
                json.dump({"model": agent.model, "history": agent.history}, f, indent=2)
            lines.append((f"[green]saved {len(agent.history)} messages to {path}[/green]", True))
        except OSError as e:
            lines.append((f"[red]save failed: {e}[/red]", True))
        return (ReplAction.CONTINUE, lines)

    if user_input.startswith("/load"):
        parts = user_input.split(maxsplit=1)
        path = parts[1].strip() if len(parts) > 1 else "history.json"
        try:
            with open(path) as f:
                data = json.load(f)
            agent.history = data.get("history", [])
            lines.append((f"[green]loaded {len(agent.history)} messages from {path}[/green]", True))
        except FileNotFoundError:
            lines.append((f"[red]file not found: {path}[/red]", True))
        except Exception as e:
            lines.append((f"[red]error loading history: {e}[/red]", True))
        return (ReplAction.CONTINUE, lines)

    if user_input.startswith("/undo"):
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2:
            keys = edit_history_keys()
            if keys:
                lines.append(("[dim]files with undo history:[/dim]", True))
                for k in keys:
                    lines.append((f"  {k}", True))
            else:
                lines.append(("[dim]no undo history available.[/dim]", True))
        else:
            path = parts[1].strip()
            result = undo_edit(path)
            color = "green" if result.startswith("OK") else "red"
            lines.append((f"[{color}]{escape(result)}[/{color}]", True))
        return (ReplAction.CONTINUE, lines)

    return (ReplAction.AGENT, lines)


def emit_lines(console: Console, items: list[ReplLine]) -> None:
    for text, markup in items:
        console.print(text, markup=markup)


def emit_rich_log(log: object, items: list[ReplLine]) -> None:
    """Append lines to Textual RichLog (widget with .write)."""
    for text, markup in items:
        if markup:
            log.write(Text.from_markup(text))
        else:
            log.write(Text(text))
