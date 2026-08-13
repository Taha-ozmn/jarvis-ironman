"""Web research pipeline — DuckDuckGo Instant Answer + extractive summary."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from memory.repository import MemoryRepository
from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult
from tools.browser_tools import USER_AGENT, fetch_page_text

SummarizerFn = Callable[[str, list[str]], str]


class ResearchTopicTool(BaseTool):
    name = "research.topic"
    description = "Research a topic: search → snippets → extractive summary"
    permission_level = PermissionLevel.LOCAL
    input_schema = {"query": {"type": "str", "required": True}}

    def __init__(
        self,
        memory: Optional[MemoryRepository] = None,
        *,
        summarizer: Optional[SummarizerFn] = None,
    ) -> None:
        self._memory = memory
        self._summarizer = summarizer

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="query required")
        save = bool(arguments.get("save_memory", False))
        try:
            snippets = collect_research_snippets(query)
        except Exception as err:
            return ToolResult(ok=False, error=f"Research failed: {err}")
        if not snippets:
            return ToolResult(
                ok=False,
                error="No research snippets available (network or empty results).",
            )
        if self._summarizer:
            try:
                summary = self._summarizer(query, snippets)
            except Exception:
                summary = extractive_summary(query, snippets)
        else:
            summary = extractive_summary(query, snippets)
        if save and self._memory is not None:
            try:
                self._memory.create(
                    f"Research «{query}»: {summary[:300]}",
                    category="research",
                    importance=2,
                )
            except Exception:
                pass
        speech = summary if len(summary) <= 280 else summary[:277] + "…"
        return ToolResult(ok=True, data=speech)


def collect_research_snippets(query: str, *, limit: int = 5) -> list[str]:
    snippets: list[str] = []
    # 1) DuckDuckGo Instant Answer API
    api = (
        "https://api.duckduckgo.com/?"
        + urllib.parse.urlencode({"q": query, "format": "json", "no_html": 1, "skip_disambig": 1})
    )
    req = urllib.request.Request(api, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        snippets.append(abstract)
    related = data.get("RelatedTopics") or []
    for item in related:
        if isinstance(item, dict) and item.get("Text"):
            snippets.append(str(item["Text"]).strip())
        elif isinstance(item, dict) and "Topics" in item:
            for sub in item.get("Topics") or []:
                if isinstance(sub, dict) and sub.get("Text"):
                    snippets.append(str(sub["Text"]).strip())
        if len(snippets) >= limit:
            break
    # 2) Optional Wikipedia summary if still thin
    if len(snippets) < 2:
        title = urllib.parse.quote(query.replace(" ", "_"))
        wiki = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
        try:
            wreq = urllib.request.Request(wiki, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(wreq, timeout=10) as wresp:
                wdata = json.loads(wresp.read().decode("utf-8", errors="replace"))
            extract = (wdata.get("extract") or "").strip()
            if extract:
                snippets.append(extract)
        except Exception:
            pass
    # dedupe
    seen: set[str] = set()
    unique: list[str] = []
    for s in snippets:
        key = s[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
        if len(unique) >= limit:
            break
    return unique


def extractive_summary(query: str, snippets: list[str], *, max_chars: int = 400) -> str:
    joined = " ".join(snippets)
    joined = " ".join(joined.split())
    if len(joined) > max_chars:
        joined = joined[:max_chars].rsplit(" ", 1)[0] + "…"
    return f"On «{query}»: {joined}"
