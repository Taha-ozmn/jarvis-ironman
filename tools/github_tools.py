"""GitHub issues/PRs via `gh` CLI or REST + GITHUB_TOKEN (never commit the token)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any, Optional

from security.permissions import PermissionLevel
from tools.base import BaseTool, ToolResult

API_ROOT = "https://api.github.com"
MISSING_AUTH = (
    "GitHub kimliği yok. `gh auth login` yapın veya proje kökündeki .env "
    "dosyasına GITHUB_TOKEN ekleyin (asla commit etmeyin). "
    "İsteğe bağlı: GITHUB_REPO=owner/name"
)


def _token() -> str:
    return (
        os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or ""
    ).strip()


def _gh_bin() -> Optional[str]:
    return shutil.which("gh")


def _run_gh(args: list[str], *, timeout: float = 25.0) -> tuple[bool, str]:
    binary = _gh_bin()
    if not binary:
        return False, "gh not found"
    try:
        result = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "gh timed out"
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode != 0:
        return False, err or out or f"gh exited {result.returncode}"
    return True, out


def resolve_repo(explicit: str = "") -> str:
    repo = (explicit or os.environ.get("GITHUB_REPO") or "").strip()
    if repo:
        return repo
    ok, out = _run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if ok and out:
        return out.strip()
    return ""


def _auth_help(err: str = "") -> str:
    extra = f" ({err[:120]})" if err else ""
    return MISSING_AUTH + extra


def _rest(path: str, *, method: str = "GET", body: Optional[dict] = None) -> tuple[bool, Any, str]:
    token = _token()
    if not token:
        return False, None, "no token"
    url = path if path.startswith("http") else f"{API_ROOT}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "jarvis-ironman",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")[:200]
        return False, None, f"HTTP {err.code}: {detail}"
    except Exception as err:
        return False, None, str(err)
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = raw
    return True, parsed, ""


def _format_items(rows: list[dict[str, Any]], *, kind: str) -> str:
    if not rows:
        return f"Açık {kind} yok."
    bits = []
    for row in rows[:8]:
        num = row.get("number")
        title = str(row.get("title") or "")[:80]
        bits.append(f"#{num} {title}".strip())
    return f"{len(rows)} {kind}: " + "; ".join(bits)


class GithubListIssuesTool(BaseTool):
    name = "github.list_issues"
    description = "List open GitHub issues (gh CLI or GITHUB_TOKEN)"
    permission_level = PermissionLevel.READ
    input_schema = {"repo": {"type": "str", "required": False}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        repo = resolve_repo(str(arguments.get("repo") or ""))
        if _gh_bin():
            args = ["issue", "list", "--limit", "10"]
            if repo:
                args.extend(["-R", repo])
            ok, out = _run_gh(args)
            if ok:
                text = out or "Açık issue yok."
                return ToolResult(ok=True, data=text[:400])
            if "gh not found" not in out.lower():
                low = out.lower()
                if "auth" in low or "login" in low or "401" in low:
                    return ToolResult(ok=False, error=_auth_help(out))
        if not _token():
            return ToolResult(ok=False, error=_auth_help())
        if not repo:
            return ToolResult(
                ok=False,
                error="Repo not set. Configure GITHUB_REPO=owner/name or pass a repo in the command.",
            )
        ok, data, err = _rest(f"/repos/{repo}/issues?state=open&per_page=10")
        if not ok:
            return ToolResult(ok=False, error=_auth_help(err))
        issues = [x for x in (data or []) if isinstance(x, dict) and "pull_request" not in x]
        return ToolResult(ok=True, data=_format_items(issues, kind="issue")[:400])


class GithubListPullsTool(BaseTool):
    name = "github.list_pulls"
    description = "List open GitHub pull requests"
    permission_level = PermissionLevel.READ
    input_schema = {"repo": {"type": "str", "required": False}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        repo = resolve_repo(str(arguments.get("repo") or ""))
        if _gh_bin():
            args = ["pr", "list", "--limit", "10"]
            if repo:
                args.extend(["-R", repo])
            ok, out = _run_gh(args)
            if ok:
                return ToolResult(ok=True, data=(out or "No open PRs.")[:400])
            if "auth" in out.lower() or "login" in out.lower():
                return ToolResult(ok=False, error=_auth_help(out))
        if not _token():
            return ToolResult(ok=False, error=_auth_help())
        if not repo:
            return ToolResult(
                ok=False,
                error="Repo not set. Configure GITHUB_REPO=owner/name.",
            )
        ok, data, err = _rest(f"/repos/{repo}/pulls?state=open&per_page=10")
        if not ok:
            return ToolResult(ok=False, error=_auth_help(err))
        rows = [x for x in (data or []) if isinstance(x, dict)]
        return ToolResult(ok=True, data=_format_items(rows, kind="PR")[:400])


class GithubCreateIssueTool(BaseTool):
    name = "github.create_issue"
    description = "Create a GitHub issue (Level 2)"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "title": {"type": "str", "required": False},
        "body": {"type": "str", "required": False},
        "repo": {"type": "str", "required": False},
        "text": {"type": "str", "required": False},
    }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        title = str(arguments.get("title") or "").strip()
        body = str(arguments.get("body") or "").strip()
        raw = str(arguments.get("text") or "").strip()
        if not title and raw:
            title = raw
            for prefix in ("issue aç", "issue olustur", "issue oluştur", "create issue"):
                if title.lower().startswith(prefix):
                    title = title[len(prefix) :].strip(" :,-")
                    break
        title = title or "JARVIS issue"
        repo = resolve_repo(str(arguments.get("repo") or ""))
        if _gh_bin():
            args = ["issue", "create", "--title", title]
            if body:
                args.extend(["--body", body])
            if repo:
                args.extend(["-R", repo])
            ok, out = _run_gh(args)
            if ok:
                return ToolResult(ok=True, data=f"Issue opened: {out[:240]}")
            if "auth" in out.lower() or "login" in out.lower():
                return ToolResult(ok=False, error=_auth_help(out))
        if not _token():
            return ToolResult(ok=False, error=_auth_help())
        if not repo:
            return ToolResult(
                ok=False,
                error="Repo not set. Configure GITHUB_REPO=owner/name.",
            )
        ok, data, err = _rest(
            f"/repos/{repo}/issues",
            method="POST",
            body={"title": title, "body": body},
        )
        if not ok or not isinstance(data, dict):
            return ToolResult(ok=False, error=_auth_help(err or "create failed"))
        num = data.get("number")
        url = data.get("html_url") or ""
        return ToolResult(ok=True, data=f"Issue #{num} opened. {url}".strip()[:400])
