#!/usr/bin/env python3
"""
Minimal coding agent CLI.

Usage:
    python cli.py [--model MODEL] [--dir DIR]
    python cli.py "one-shot prompt"

Commands inside the REPL:
    /reset   — clear conversation history
    /quit    — exit
    /history — show turn count
"""

import argparse
import os
import sys

from rich.console import Console
from rich.rule import Rule

from agent import Agent

console = Console()


BANNER = """\
 ╔══════════════════════════════╗
 ║   minimal coding agent  🤖   ║
 ╚══════════════════════════════╝
  /reset  clear history   /quit  exit
"""


def run_interactive(agent: Agent) -> None:
    console.print(BANNER, style="bold cyan")
    console.print(f"  model : [bold]{agent.model}[/bold]")
    console.print(f"  cwd   : [bold]{os.path.abspath(agent.cwd)}[/bold]\n")

    while True:
        try:
            user_input = console.input("[bold green]you>[/bold green] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]bye.[/dim]")
            break

        if not user_input:
            continue

        # REPL commands
        if user_input == "/quit":
            console.print("[dim]bye.[/dim]")
            break
        if user_input == "/reset":
            agent.reset()
            console.print("[yellow]history cleared.[/yellow]")
            continue
        if user_input == "/history":
            turns = sum(1 for m in agent.history if m["role"] == "user")
            console.print(f"[dim]{turns} user turn(s) in history.[/dim]")
            continue

        console.print(Rule(style="dim"))
        console.print("[bold blue]agent>[/bold blue] ", end="")

        # Stream the response
        collected = []
        try:
            for chunk in agent.stream_turn(user_input):
                # Tool call lines are prefixed with \n[tool:
                if chunk.startswith("\n\n[tool:"):
                    # Print accumulated text first
                    if collected:
                        pass  # already printed char-by-char below
                    console.print(chunk, style="dim yellow", end="")
                else:
                    console.print(chunk, end="", style="white")
                collected.append(chunk)
        except KeyboardInterrupt:
            console.print("\n[yellow](interrupted)[/yellow]")

        console.print()  # newline after streaming
        console.print(Rule(style="dim"))


def run_oneshot(agent: Agent, prompt: str) -> None:
    """Run a single prompt and print the result (no REPL)."""
    for chunk in agent.stream_turn(prompt):
        print(chunk, end="", flush=True)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minimal coding agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("prompt", nargs="?", help="One-shot prompt (skips REPL)")
    parser.add_argument("--model", default="claude-opus-4-6", help="Claude model ID")
    parser.add_argument(
        "--dir", default=".", help="Working directory to run in (default: .)"
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[bold red]Error:[/bold red] ANTHROPIC_API_KEY environment variable not set."
        )
        sys.exit(1)

    agent = Agent(model=args.model, cwd=args.dir)

    if args.prompt:
        run_oneshot(agent, args.prompt)
    else:
        run_interactive(agent)


if __name__ == "__main__":
    main()
