#!/usr/bin/env python3
"""
Coding agent CLI.

Usage:
    python cli.py [--model MODEL] [--dir DIR] [--max-tokens N] [--yolo] [--trace FILE]
    python cli.py [--tui]   # full-screen Textual UI (optional)
    python cli.py "one-shot prompt"

REPL commands:
    /reset            — clear conversation history and token counts
    /quit             — exit
    /history          — show turn count
    /cost             — show session token usage and estimated cost
    /model <id>       — switch model mid-session
    /tools            — list available tools (built-in + plugins)
    /undo <path>      — revert last agent write/edit to <path>
    /yolo             — toggle bash approval mode
    /save [file]      — save conversation history to JSON (default: history.json)
    /load [file]      — load conversation history from JSON (default: history.json)
    /compact          — summarize history to free context space
    /tasks            — show current task list
    /reload           — reload plugins from the plugins/ directory
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from agent import Agent
from repl_dispatch import ReplAction, cost_for, emit_lines, format_turn_cost_line, repl_dispatch

console = Console()

# ---------------------------------------------------------------------------
# Slash completion (prompt-toolkit)
# ---------------------------------------------------------------------------
_SLASH_WORDS = [
    "/quit",
    "/reset",
    "/history",
    "/cost",
    "/tools",
    "/tasks",
    "/compact",
    "/reload",
    "/yolo",
    "/model",
    "/save",
    "/load",
    "/undo",
]


def _history_file() -> Path:
    d = Path.home() / ".cache" / "coding-agent"
    d.mkdir(parents=True, exist_ok=True)
    return d / "repl_history"


def banner_panel() -> Panel:
    return Panel.fit(
        "[bold cyan]coding agent[/bold cyan]  🤖\n\n"
        "[dim]/yolo[/dim]  bash approval   [dim]/reset[/dim]  history   [dim]/cost[/dim]  tokens\n"
        "[dim]/tools[/dim]  list tools     [dim]/save[/dim] · [dim]/load[/dim]  session JSON\n"
        "[dim]/compact[/dim]  compress ctx  [dim]/tasks[/dim]  task list  [dim]/reload[/dim]  plugins\n"
        "[dim]/quit[/dim]  exit",
        title="[bold]help[/bold]",
        border_style="cyan",
        padding=(1, 2),
    )


# ---------------------------------------------------------------------------
# Pricing helpers (re-export for one-shot / turn cost display)
# ---------------------------------------------------------------------------


def _show_turn_cost(agent: Agent) -> None:
    console.print(format_turn_cost_line(agent))


def _make_approval_fn(yolo_flag: list[bool]) -> object:
    """Return a closure that checks yolo_flag[0] before prompting."""

    def approve(command: str) -> bool:
        if yolo_flag[0]:
            return True
        console.print(f"\n[yellow bold]bash:[/yellow bold] {command}")
        try:
            answer = console.input("[yellow]  approve? [y/N]:[/yellow] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            answer = ""
        return answer in ("y", "yes")

    return approve


def _run_agent_turn(agent: Agent, user_input: str) -> None:
    console.print(Rule(style="dim"))
    console.print("[bold blue]agent>[/bold blue] ", end="")

    try:
        for chunk in agent.stream_turn(user_input):
            if chunk.startswith("\n\n[tool:"):
                console.print(chunk, style="dim yellow", end="", markup=False)
            else:
                console.print(chunk, end="", style="white", markup=False)
    except KeyboardInterrupt:
        console.print("\n[yellow](interrupted)[/yellow]")

    console.print()
    _show_turn_cost(agent)
    console.print(Rule(style="dim"))


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


def run_interactive(agent: Agent) -> None:
    console.print(banner_panel())
    console.print(f"  model  : [bold]{agent.model}[/bold]")
    console.print(f"  cwd    : [bold]{os.path.abspath(agent.cwd)}[/bold]")

    yolo_flag: list[bool] = [getattr(agent, "_yolo_init", False)]
    agent.bash_approval_fn = _make_approval_fn(yolo_flag)  # type: ignore[assignment]

    console.print(
        f"  bash   : [bold]{'auto-approve (yolo)' if yolo_flag[0] else 'ask before each command'}[/bold]\n"
    )

    completer = WordCompleter(_SLASH_WORDS, ignore_case=True, match_middle=True)
    session = PromptSession(
        history=FileHistory(str(_history_file())),
        completer=completer,
        complete_while_typing=False,
    )

    while True:
        try:
            user_input = session.prompt("you> ").strip()
        except KeyboardInterrupt:
            console.print("\n[dim]bye.[/dim]")
            break
        except EOFError:
            console.print("\n[dim]bye.[/dim]")
            break

        if not user_input:
            continue

        action, lines = repl_dispatch(user_input, agent, yolo_flag)
        if action == ReplAction.QUIT:
            emit_lines(console, lines)
            break
        if action == ReplAction.CONTINUE:
            emit_lines(console, lines)
            continue

        _run_agent_turn(agent, user_input)


# ---------------------------------------------------------------------------
# One-shot
# ---------------------------------------------------------------------------


def run_oneshot(agent: Agent, prompt: str) -> None:
    for chunk in agent.stream_turn(prompt):
        print(chunk, end="", flush=True)
    print()
    turn_cost = cost_for(agent.model, agent.turn_input_tokens, agent.turn_output_tokens)
    print(
        f"\n[tokens ↑{agent.turn_input_tokens:,} ↓{agent.turn_output_tokens:,}"
        f"  cost ${turn_cost:.4f}]",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Coding agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("prompt", nargs="?", help="One-shot prompt (skips REPL)")
    parser.add_argument("--model", default="claude-opus-4-6", help="Claude model ID")
    parser.add_argument("--dir", default=".", help="Working directory (default: .)")
    parser.add_argument(
        "--max-tokens", type=int, default=8096, help="Max output tokens (default: 8096)"
    )
    parser.add_argument(
        "--yolo", action="store_true", help="Auto-approve all bash commands (no prompts)"
    )
    parser.add_argument(
        "--trace",
        metavar="FILE",
        default=None,
        help="Log all tool calls to a JSONL file for debugging (e.g. --trace trace.jsonl)",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Run interactive session in a Textual full-screen UI (requires: textual)",
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[bold red]Error:[/bold red] ANTHROPIC_API_KEY environment variable not set."
        )
        sys.exit(1)

    agent = Agent(
        model=args.model,
        cwd=args.dir,
        max_tokens=args.max_tokens,
        trace_file=args.trace,
    )
    agent._yolo_init = args.yolo  # type: ignore[attr-defined]
    if args.trace:
        console.print(f"[dim]tracing tool calls → {args.trace}[/dim]")

    if args.prompt:
        yolo_flag = [args.yolo]
        agent.bash_approval_fn = _make_approval_fn(yolo_flag)  # type: ignore[assignment]
        run_oneshot(agent, args.prompt)
    elif args.tui:
        try:
            from tui import run_textual_interactive
        except ImportError as e:
            console.print(
                "[red]--tui requires optional dependencies.[/red] "
                "Install with: `pip install textual`"
            )
            console.print(f"[dim]{e}[/dim]")
            sys.exit(1)
        run_textual_interactive(agent)
    else:
        run_interactive(agent)


if __name__ == "__main__":
    main()
