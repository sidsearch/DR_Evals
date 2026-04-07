"""
Web search tools — Tavily and SerpAPI providers.

Set ONE or BOTH of these environment variables to enable search:
  TAVILY_API_KEY   — https://app.tavily.com
  SERPAPI_API_KEY  — https://serpapi.com

Tools registered:
  web_search    — auto-selects Tavily if available, falls back to SerpAPI
  tavily_search — Tavily directly (requires TAVILY_API_KEY)
  serp_search   — SerpAPI directly (requires SERPAPI_API_KEY)
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from tool_registry import tool


# ---------------------------------------------------------------------------
# Tavily
# ---------------------------------------------------------------------------

def _tavily(query: str, max_results: int = 5, search_depth: str = "basic") -> str:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return "ERROR: TAVILY_API_KEY is not set"

    payload = json.dumps({
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": True,
    }).encode()

    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        return f"ERROR: Tavily HTTP {e.code}: {body}"
    except Exception as e:
        return f"ERROR: {e}"

    lines = []
    if data.get("answer"):
        lines.append(f"Answer: {data['answer']}\n")
    for i, r in enumerate(data.get("results", []), 1):
        lines.append(f"{i}. {r.get('title', '(no title)')}")
        lines.append(f"   URL: {r.get('url', '')}")
        snippet = r.get("content", "").strip()
        if snippet:
            # Trim long snippets
            lines.append(f"   {snippet[:300]}{'…' if len(snippet) > 300 else ''}")
        lines.append("")
    return "\n".join(lines).strip() or "(no results)"


# ---------------------------------------------------------------------------
# SerpAPI
# ---------------------------------------------------------------------------

def _serp(query: str, num: int = 5, engine: str = "google") -> str:
    api_key = os.environ.get("SERPAPI_API_KEY", "")
    if not api_key:
        return "ERROR: SERPAPI_API_KEY is not set"

    params = urllib.parse.urlencode({
        "api_key": api_key,
        "q": query,
        "num": num,
        "engine": engine,
    })
    url = f"https://serpapi.com/search?{params}"

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        return f"ERROR: SerpAPI HTTP {e.code}: {body}"
    except Exception as e:
        return f"ERROR: {e}"

    lines = []
    # Answer box (if present)
    ab = data.get("answer_box", {})
    if ab.get("answer"):
        lines.append(f"Answer: {ab['answer']}\n")
    elif ab.get("snippet"):
        lines.append(f"Answer: {ab['snippet']}\n")

    for i, r in enumerate(data.get("organic_results", []), 1):
        lines.append(f"{i}. {r.get('title', '(no title)')}")
        lines.append(f"   URL: {r.get('link', '')}")
        snippet = r.get("snippet", "").strip()
        if snippet:
            lines.append(f"   {snippet[:300]}{'…' if len(snippet) > 300 else ''}")
        lines.append("")
    return "\n".join(lines).strip() or "(no results)"


# ---------------------------------------------------------------------------
# Registered tools
# ---------------------------------------------------------------------------

@tool
def web_search(query: str, num_results: int = 5) -> str:
    """Search the web for up-to-date information. Uses Tavily if TAVILY_API_KEY is set, otherwise SerpAPI.

    Args:
        query: Search query string.
        num_results: Number of results to return (default 5).
    """
    if os.environ.get("TAVILY_API_KEY"):
        return _tavily(query, max_results=num_results)
    if os.environ.get("SERPAPI_API_KEY"):
        return _serp(query, num=num_results)
    return (
        "ERROR: no search provider configured. "
        "Set TAVILY_API_KEY or SERPAPI_API_KEY."
    )


@tool
def tavily_search(query: str, num_results: int = 5, search_depth: str = "basic") -> str:
    """Search the web using Tavily. Requires TAVILY_API_KEY.

    Args:
        query: Search query string.
        num_results: Number of results to return (default 5).
        search_depth: basic (faster) or advanced (more thorough, costs 2 credits).
    """
    return _tavily(query, max_results=num_results, search_depth=search_depth)


@tool
def serp_search(query: str, num_results: int = 5, engine: str = "google") -> str:
    """Search the web using SerpAPI. Requires SERPAPI_API_KEY.

    Args:
        query: Search query string.
        num_results: Number of results to return (default 5).
        engine: Search engine to use: google, bing, duckduckgo, etc.
    """
    return _serp(query, num=num_results, engine=engine)
