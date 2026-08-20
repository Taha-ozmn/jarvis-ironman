"""Register Phase 3–6 tools."""

from __future__ import annotations

from typing import Any, Callable, Optional

from security.permissions import PermissionLevel
from tools.agent_tools import CodingAnalyzeAgentTool, ResearchAgentTool
from tools.automation_tools import (
    AutomationCreateTool,
    AutomationDeleteTool,
    AutomationDisableTool,
    AutomationEnableTool,
    AutomationListTool,
    AutomationRunTool,
    BriefingTool,
)
from tools.browser_tools import (
    BrowserClickTool,
    BrowserFillFormTool,
    BrowserGetPageTextTool,
    BrowserListTabsTool,
    BrowserOpenUrlTool,
    BrowserSearchTool,
)
from tools.dev_tools import AnalyzeRepoTool, DevRunCommandTool, FixCycleTool, RunTestsTool
from tools.diagnostics_tools import DiagnosticsHealthTool, SystemHealthTool
from tools.fs_tools import FsCreateTool, FsListTool, FsMoveTool, FsReadTool, FsWriteTool
from tools.git_tools import (
    GitAddTool,
    GitBranchTool,
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitPushTool,
    GitStatusTool,
)
from tools.macos_tools import (
    ClipboardReadTool,
    ClipboardWriteTool,
    CloseAppTool,
    DateTool,
    FinderRevealTool,
    ListAppsTool,
    NotifyTool,
    OpenAppTool,
    ProcessListTool,
    ShellTool,
    TimeTool,
    VolumeTool,
    WebSearchTool,
)
from tools.mail_tools import MailComposeTool, MailInboxSummaryTool, MailOpenTool
from tools.media_tools import MediaPlayTool
from tools.memory_tools import (
    MemoryAboutUserTool,
    MemoryForgetTool,
    MemoryListTool,
    MemorySaveTool,
    MemorySearchTool,
    MemorySessionCaptureTool,
    PreferenceApplyTool,
)
from tools.calendar_tools import CalendarCreateEventTool, CalendarListTodayTool
from tools.github_tools import GithubCreateIssueTool, GithubListIssuesTool, GithubListPullsTool
from tools.permissions_tools import CheckPermissionsTool
from tools.plan_tools import PlanRunTool, SystemBackupTool
from tools.patch_tools import ApplyPatchTool
from tools.project_tools import ProjectGetTool, ProjectListTool, ProjectSetActiveTool
from tools.registry import ToolRegistry
from tools.research_tools import ResearchTopicTool
from tools.weather_tools import WeatherTool
from tools.screen_tools import ScreenCaptureTool, ScreenDescribeTool
from tools.task_tools import TaskCompleteTool, TaskCreateTool, TaskListTool


def register_phase3_tools(
    registry: ToolRegistry,
    *,
    macos: Any,
    memory: Any,
    tasks: Any,
    health_fn: Callable[[], dict],
    automation: Any = None,
    briefing: Any = None,
    projects: Any = None,
    working_dir: Optional[Callable[[], Any]] = None,
    backup: Any = None,
    plan_runner: Any = None,
    llm: Any = None,
    jarvis2_config: Optional[dict[str, Any]] = None,
    jarvis_language: str = "en-GB",
    on_preference_applied: Optional[Callable[[str], None]] = None,
    screen_context_getter: Optional[Callable[[], dict]] = None,
    memory_layers: Any = None,
    research_agent_runner: Any = None,
    coding_agent_runner: Any = None,
    session_capture_setter: Any = None,
) -> None:
    """Register real tools across phases."""
    from pathlib import Path

    wd = working_dir or (lambda: Path.cwd())
    j2_cfg = jarvis2_config or {}
    weather_default = str(j2_cfg.get("weather_default_location") or "")
    weather_timeout = float(j2_cfg.get("weather_timeout", 8.0))

    # Memory layers facade (optional — built if missing)
    layers = memory_layers
    if layers is None and memory is not None:
        from memory.layers import MemoryLayers

        layers = MemoryLayers(memory)

    real_tools: list = [
        OpenAppTool(macos),
        ListAppsTool(macos),
        CloseAppTool(macos),
        TimeTool(),
        DateTool(),
        VolumeTool(macos),
        WeatherTool(default_location=weather_default, timeout=weather_timeout),
        WebSearchTool(),
        ShellTool(macos),
        ClipboardReadTool(),
        ClipboardWriteTool(),
        NotifyTool(),
        ProcessListTool(),
        FinderRevealTool(),
        MailOpenTool(),
        MailInboxSummaryTool(),
        MailComposeTool(),
        CalendarListTodayTool(),
        CalendarCreateEventTool(),
        GithubListIssuesTool(),
        GithubListPullsTool(),
        GithubCreateIssueTool(),
        CheckPermissionsTool(),
        MemorySearchTool(memory),
        MemorySaveTool(memory),
        PreferenceApplyTool(
            memory,
            language=jarvis_language,
            on_applied=on_preference_applied,
        ),
        MemoryListTool(memory),
        MemoryAboutUserTool(layers, language=jarvis_language),
        MemoryForgetTool(layers),
        TaskCreateTool(tasks),
        TaskListTool(tasks),
        TaskCompleteTool(tasks),
        FsListTool(wd),
        FsReadTool(wd),
        FsWriteTool(wd),
        FsCreateTool(wd),
        FsMoveTool(wd),
        SystemHealthTool(),
        DiagnosticsHealthTool(health_fn),
        BrowserOpenUrlTool(),
        BrowserListTabsTool(),
        BrowserSearchTool(),
        BrowserGetPageTextTool(),
        BrowserFillFormTool(),
        BrowserClickTool(),
        MediaPlayTool(),
        ResearchTopicTool(memory),
        ScreenCaptureTool(),
        ScreenDescribeTool(context_getter=screen_context_getter),
        GitStatusTool(wd),
        GitDiffTool(wd),
        GitBranchTool(wd),
        GitLogTool(wd),
        GitAddTool(wd),
        GitCommitTool(wd),
        GitPushTool(wd),
        AnalyzeRepoTool(wd),
        RunTestsTool(wd),
        DevRunCommandTool(wd),
        FixCycleTool(wd),
        ApplyPatchTool(wd, llm=llm),
    ]
    if research_agent_runner is not None:
        real_tools.append(ResearchAgentTool(research_agent_runner))
    if coding_agent_runner is not None:
        real_tools.append(CodingAnalyzeAgentTool(coding_agent_runner))
    if session_capture_setter is not None:
        real_tools.append(MemorySessionCaptureTool(session_capture_setter))
    if backup is not None:
        real_tools.append(SystemBackupTool(backup))
    if plan_runner is not None:
        real_tools.append(PlanRunTool(plan_runner))
    if projects is not None:
        real_tools.extend(
            [
                ProjectListTool(projects),
                ProjectGetTool(projects),
                ProjectSetActiveTool(projects),
            ]
        )
    if automation is not None:
        real_tools.extend(
            [
                AutomationCreateTool(automation),
                AutomationListTool(automation),
                AutomationEnableTool(automation),
                AutomationDisableTool(automation),
                AutomationDeleteTool(automation),
                AutomationRunTool(automation),
            ]
        )
    if briefing is not None:
        real_tools.append(BriefingTool(briefing))

    for tool in real_tools:
        registry.register(tool)
