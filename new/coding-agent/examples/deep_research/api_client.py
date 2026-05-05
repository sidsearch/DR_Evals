"""
Deep Research Agent — example API client.

Shows how to call both endpoints:
  1. /research/stream  — Server-Sent Events (recommended for long research)
  2. /research         — blocking JSON response

Usage:
    # Stream (prints output as it arrives):
    python api_client.py "fusion energy advances 2024"

    # Sync (waits for the full report):
    python api_client.py --sync "EU AI regulation overview"

    # Custom server URL:
    python api_client.py --url http://myserver:8000 "topic here"
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


DEFAULT_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Streaming client (SSE)
# ---------------------------------------------------------------------------

def research_stream(topic: str, output_dir: str = "/tmp/research_reports", base_url: str = DEFAULT_URL) -> None:
    """
    Call POST /research/stream and print output as it arrives.

    The server sends Server-Sent Events. Each line looks like:
        data: {"text": "some output chunk"}
    The final event:
        event: done
        data: {"done": true, "input_tokens": 1234, "output_tokens": 567}
    """
    url = f"{base_url}/research/stream"
    body = json.dumps({"topic": topic, "output_dir": output_dir}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    print(f"[streaming from {url}]\n")

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            event_type = "data"
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")

                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                    continue

                if line.startswith("data:"):
                    payload_str = line[len("data:"):].strip()
                    try:
                        payload = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue

                    if event_type == "done":
                        print(f"\n\n{'─' * 60}")
                        print(f"Research complete.")
                        print(f"Tokens — input: {payload.get('input_tokens', '?'):,}  "
                              f"output: {payload.get('output_tokens', '?'):,}")
                        return

                    if event_type == "error":
                        print(f"\nERROR from server: {payload.get('error')}", file=sys.stderr)
                        sys.exit(1)

                    # Normal data event — print the text chunk
                    print(payload.get("text", ""), end="", flush=True)
                    event_type = "data"  # reset for next event

    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[interrupted]")


# ---------------------------------------------------------------------------
# Blocking client (JSON)
# ---------------------------------------------------------------------------

def research_sync(topic: str, output_dir: str = "/tmp/research_reports", base_url: str = DEFAULT_URL) -> dict:
    """
    Call POST /research and return the full JSON response.

    Returns the parsed JSON dict:
      {
        "topic": "...",
        "report_path": "/tmp/research_reports/report-<slug>.md",
        "output": "full agent output",
        "input_tokens": 1234,
        "output_tokens": 567
      }
    """
    url = f"{base_url}/research"
    body = json.dumps({"topic": topic, "output_dir": output_dir}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"[calling {url} — waiting for full report...]\n")

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Deep Research Agent API client")
    parser.add_argument("topic", nargs="+", help="Topic to research")
    parser.add_argument("--sync", action="store_true", help="Use blocking /research endpoint instead of SSE")
    parser.add_argument("--output", "-o", default="/tmp/research_reports", help="Output directory for reports")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"API base URL (default: {DEFAULT_URL})")
    args = parser.parse_args()

    topic = " ".join(args.topic)

    if args.sync:
        result = research_sync(topic, output_dir=args.output, base_url=args.url)
        print(result["output"])
        print(f"\n{'─' * 60}")
        print(f"Report saved to: {result['report_path']}")
        print(f"Tokens — input: {result['input_tokens']:,}  output: {result['output_tokens']:,}")
    else:
        research_stream(topic, output_dir=args.output, base_url=args.url)


if __name__ == "__main__":
    main()
