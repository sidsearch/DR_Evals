"""
Research-specific tools for the deep research agent.

Tools:
  fetch_url   — download and extract clean text from any URL
  save_note   — accumulate key findings during a research session
  list_notes  — review all saved notes before final synthesis
"""

import sys
import html
import re
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from tool_registry import tool

_NOTES: list[dict] = []


@tool
def fetch_url(url: str, max_chars: int = 8000) -> str:
    """Fetch and extract the readable text from a web page.

    Args:
        url: The URL to fetch.
        max_chars: Maximum characters to return (default 8000).
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; research-agent/1.0)",
                "Accept": "text/html,application/xhtml+xml,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            charset = resp.headers.get_content_charset("utf-8") or "utf-8"
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        return f"ERROR: HTTP {e.code} fetching {url}"
    except Exception as e:
        return f"ERROR: {e}"

    if "text/html" in content_type or url.endswith((".html", ".htm", "/")):
        text = _html_to_text(raw)
    else:
        text = raw

    truncated = len(text) > max_chars
    text = text[:max_chars]
    if truncated:
        text += f"\n\n[... content truncated at {max_chars:,} chars ...]"

    return f"[Content from {url}]\n\n{text}"


def _html_to_text(src: str) -> str:
    """Strip HTML and return clean, readable text."""
    # Drop script / style blocks entirely
    src = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", src, flags=re.DOTALL | re.IGNORECASE)
    # Turn block-level tags into newlines for readability
    src = re.sub(r"<(br|p|div|h[1-6]|li|tr|blockquote)[^>]*/?>", "\n", src, flags=re.IGNORECASE)
    # Remove all remaining tags
    src = re.sub(r"<[^>]+>", "", src)
    # Decode HTML entities (&amp; &lt; &#160; etc.)
    src = html.unescape(src)
    # Collapse blank lines and strip trailing whitespace
    lines = [ln.strip() for ln in src.splitlines()]
    lines = [ln for ln in lines if ln]
    # De-duplicate consecutive identical lines (nav menus repeat a lot)
    deduped: list[str] = []
    for ln in lines:
        if not deduped or ln != deduped[-1]:
            deduped.append(ln)
    return "\n".join(deduped)


@tool
def save_note(content: str, source_url: str = "") -> str:
    """Save a research finding or key insight for later synthesis.

    Args:
        content: The note — a fact, quote, statistic, or insight.
        source_url: The URL this finding came from (highly recommended).
    """
    _NOTES.append({"content": content, "source": source_url})
    return f"OK: saved note #{len(_NOTES)}"


@tool
def list_notes() -> str:
    """List all research notes saved so far in this session."""
    if not _NOTES:
        return "(no notes saved yet)"
    lines: list[str] = []
    for i, note in enumerate(_NOTES, 1):
        lines.append(f"### Note {i}")
        lines.append(note["content"])
        if note["source"]:
            lines.append(f"Source: {note['source']}")
        lines.append("")
    return "\n".join(lines).strip()
