"""
Optional Textual full-screen UI. Install: pip install textual
Run: python cli.py --tui
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from repl_dispatch import ReplAction, emit_rich_log, format_turn_cost_line, repl_dispatch

if TYPE_CHECKING:
    from agent import Agent


def run_textual_interactive(agent: "Agent") -> None:
    from cli import _make_approval_fn, banner_panel
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.widgets import Footer, Header, Input, RichLog
    from textual import work

    class CodingAgentApp(App[None]):
        CSS = """
        #main { width: 100%; height: 100%; }
        RichLog { height: 1fr; min-height: 8; }
        Input { dock: bottom; margin: 0 1; }
        """

        BINDINGS = [
            Binding("ctrl+q", "quit", "Quit", show=True),
        ]

        def __init__(self, agent: "Agent") -> None:
            super().__init__()
            self.agent = agent
            self.yolo_flag: list[bool] = [getattr(agent, "_yolo_init", False)]
            agent.bash_approval_fn = _make_approval_fn(self.yolo_flag)  # type: ignore[assignment]

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Vertical(id="main"):
                yield RichLog(id="log", highlight=False, markup=False, wrap=True, auto_scroll=True)
                yield Input(placeholder="Message or /command… (Tab completes /commands)", id="inp")
            yield Footer()

        def on_mount(self) -> None:
            log = self.query_one("#log", RichLog)
            log.write(banner_panel())
            log.write(Text(""))
            log.write(
                Text.from_markup(
                    f"  model  [bold]{self.agent.model}[/bold]\n"
                    f"  cwd    [bold]{os.path.abspath(self.agent.cwd)}[/bold]\n"
                    f"  bash   [bold]{'auto-approve (yolo)' if self.yolo_flag[0] else 'ask before each command'}[/bold]"
                )
            )
            log.write(Text(""))
            log.write(Panel.fit("[dim]Ctrl+Q quit · Tab complete slash commands[/dim]", border_style="dim"))

        def action_quit(self) -> None:
            self.exit()

        def _render_agent_turn(self, combined: str) -> None:
            log = self.query_one("#log", RichLog)
            log.write(Rule(style="dim"))
            log.write(Text("agent> ", style="bold blue"))
            log.write(Text(combined))
            log.write(Rule(style="dim"))
            log.write(Text.from_markup(format_turn_cost_line(self.agent)))
            log.write(Rule(style="dim"))

        def _render_error(self, err: BaseException) -> None:
            log = self.query_one("#log", RichLog)
            log.write(Text(f"Error: {err}", style="bold red"))

        @work(thread=True, exclusive=True)
        def run_turn(self, text: str) -> None:
            parts: list[str] = []
            try:
                for chunk in self.agent.stream_turn(text):
                    parts.append(chunk)
            except Exception as e:
                self.call_from_thread(self._render_error, e)
                return
            combined = "".join(parts)
            self.call_from_thread(self._render_agent_turn, combined)

        async def on_input_submitted(self, event: Input.Submitted) -> None:
            text = event.value.strip()
            inp = self.query_one("#inp", Input)
            inp.value = ""
            if not text:
                return

            log = self.query_one("#log", RichLog)
            log.write(Text.from_markup(f"[bold green]you>[/bold green] {text}"))

            action, lines = repl_dispatch(text, self.agent, self.yolo_flag)
            if action == ReplAction.QUIT:
                emit_rich_log(log, lines)
                self.exit()
                return
            if action == ReplAction.CONTINUE:
                emit_rich_log(log, lines)
                return

            inp.disabled = True
            try:
                worker = self.run_turn(text)
                await worker.wait()
            finally:
                inp.disabled = False

    CodingAgentApp(agent).run()
