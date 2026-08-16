"""Register Phase 3–6 tools."""

from __future__ import annotations

from typing import Any, Callable, Optional

from security.permissions import PermissionLevel
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
    BrowserNavigateTool,
    BrowserOpenUrlTool,
    BrowserSearchTool,
)
from tools.dev_tools import AnalyzeRepoTool, DevRunCommandTool, FixCycleTool, RunTestsTool
from tools.diagnostics_tools import DiagnosticsHealthTool
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
    DateTool,
    OpenAppTool,
    ShellTool,
    TimeTool,
    VolumeTool,
    WebSearchTool,
)
from tools.memory_tools import MemoryListTool, MemorySaveTool, MemorySearchTool
from tools.plan_tools import PlanRunTool, SystemBackupTool
from tools.patch_tools import ApplyPatchTool
from tools.project_tools import ProjectGetTool, ProjectListTool, ProjectSetActiveTool
from tools.registry import ToolRegistry
from tools.research_tools import ResearchTopicTool
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
) -> None:
    """Register real tools across phases."""
    from pathlib import Path

    wd = working_dir or (lambda: Path.cwd())

    real_tools: list = [
        OpenAppTool(macos),
        TimeTool(),
        DateTool(),
        VolumeTool(macos),
        WebSearchTool(),
        ShellTool(macos),
        MemorySearchTool(memory),
        MemorySaveTool(memory),
        MemoryListTool(memory),
        TaskCreateTool(tasks),
        TaskListTool(tasks),
        TaskCompleteTool(tasks),
        FsListTool(wd),
        FsReadTool(wd),
        FsWriteTool(wd),
        FsCreateTool(wd),
        FsMoveTool(wd),
        DiagnosticsHealthTool(health_fn),
        BrowserOpenUrlTool(),
        BrowserNavigateTool(),
        BrowserSearchTool(),
        BrowserGetPageTextTool(),
        BrowserFillFormTool(),
        BrowserClickTool(),
        ResearchTopicTool(memory),
        ScreenCaptureTool(),
        ScreenDescribeTool(),
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
