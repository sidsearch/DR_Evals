"""
ResearchAgent — a deep research agent built on the coding-agent harness.

Extends the base Agent class with:
  - A research-focused system prompt (plan → search → read → notes → report)
  - fetch_url, save_note, list_notes tools
  - web_search loaded from the harness plugins/
"""

import sys
from pathlib import Path

# Add the main harness to sys.path so we can import Agent, tool_registry, tools
_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_HARNESS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import Agent
from tools import TOOLS
from tool_registry import load_plugins, registry_tools

# Load web_search / tavily_search / serp_search from the harness plugins/
load_plugins(str(_HARNESS_DIR / "plugins"))

# Load research-specific tools (fetch_url, save_note, list_notes)
__import__("research_tools")  # registers @tool functions as a side-effect

# Merge everything into the shared TOOLS dict used by the harness dispatch()
for _name, _entry in registry_tools().items():
    if _name not in TOOLS:
        TOOLS[_name] = _entry


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_RESEARCH_SYSTEM = """\
You are a deep research assistant. Your job is to produce a thorough, well-cited \
report on any topic the user gives you.

## Research Methodology

Work through these phases in order:

### Phase 1 — Plan
Decompose the topic into 4-6 specific research questions.
Call task_create for each question so you can track progress.

### Phase 2 — Search
For each question, run 1-3 targeted web_search queries.
Good searches combine the topic + specific angle:
  "fusion energy recent breakthroughs 2024"
  "fusion energy commercial viability challenges"
  "fusion energy investment funding"

### Phase 3 — Read
For the 2-3 most relevant search results per question, call fetch_url to get the \
full page content. Prioritise authoritative sources: academic papers, government \
reports, major news outlets, official documentation.

### Phase 4 — Take Notes
After each fetch_url, call save_note to record key findings.
Each note should contain: the insight/fact, and always include source_url.

### Phase 5 — Synthesize
After completing all tasks, call list_notes to review everything you've gathered.
Then write the final report with write_file.

## Report Format

Save the report as a Markdown file. Use this structure:

```
# Research Report: <Topic>

*Generated: <date>*

## Executive Summary
2–3 paragraphs covering the most important findings.

## Background
Why this topic matters and relevant context.

## Key Findings

### <Theme 1>
<finding with inline citations [Source](url)>

### <Theme 2>
...

## Analysis & Implications
What the findings mean; open questions; caveats.

## Conclusion
Key takeaways in 1–2 paragraphs.

## Sources
- [Title](url) — what this contributed to the report
```

Be accurate. Acknowledge uncertainty. Cite sources inline using Markdown links.
"""


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class ResearchAgent(Agent):
    """Agent specialised for multi-step web research and report generation."""

    def __init__(self, output_dir: str = "."):
        super().__init__()
        self.output_dir = str(Path(output_dir).resolve())

    def _system(self) -> str:
        """Return a research-focused system prompt (overrides the coding-focused base)."""
        return (
            f"You are a deep research assistant running in a terminal.\n"
            f"Output directory for reports: {self.output_dir}\n\n"
            + _RESEARCH_SYSTEM
        )

    def research(self, topic: str) -> None:
        """Stream a full research session on *topic* to stdout."""
        prompt = (
            f"Research this topic comprehensively: **{topic}**\n\n"
            f"Follow the five-phase methodology in your system instructions.\n"
            f"Save the finished report to: {self.output_dir}/report_<slug>.md\n"
            f"where <slug> is a short kebab-case version of the topic."
        )
        for chunk in self.stream_turn(prompt):
            print(chunk, end="", flush=True)
        print()  # final newline
