"""
Deep Research Agent — CLI entry point.

Usage:
    python run.py "What are the latest advances in fusion energy?"
    python run.py                         # prompts for a topic interactively
    python run.py --output ./reports "topic"

Requirements:
    Set at least one search API key in your environment:
      export TAVILY_API_KEY="tvly-..."        # https://app.tavily.com  (recommended)
      export SERPAPI_API_KEY="..."            # https://serpapi.com     (fallback)
    And your Anthropic key:
      export ANTHROPIC_API_KEY="sk-ant-..."
"""

import argparse
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_DIR))

from research_agent import ResearchAgent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deep Research Agent — researches a topic and writes a Markdown report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("topic", nargs="*", help="Topic to research")
    parser.add_argument(
        "--output", "-o",
        default=str(_DIR),
        help="Directory to save the report (default: this script's directory)",
    )
    args = parser.parse_args()

    topic = " ".join(args.topic).strip()
    if not topic:
        try:
            topic = input("Research topic: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
    if not topic:
        parser.print_help()
        sys.exit(1)

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'═' * 60}")
    print(f"  Deep Research Agent")
    print(f"  Topic : {topic}")
    print(f"  Output: {output_dir}")
    print(f"{'═' * 60}\n")

    agent = ResearchAgent(output_dir=str(output_dir))

    try:
        agent.research(topic)
    except KeyboardInterrupt:
        print("\n\n[Interrupted]")

    print(f"\n{'─' * 60}")
    print(f"Token usage — input: {agent.turn_input_tokens:,}  output: {agent.turn_output_tokens:,}")
    print(f"Session total — input: {agent.total_input_tokens:,}  output: {agent.total_output_tokens:,}")


if __name__ == "__main__":
    main()
