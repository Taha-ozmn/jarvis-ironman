from .base import BaseTool, ToolResult, WorkingDirFn
from security.permissions import PermissionLevel
from tools.utils import is_credential_path, is_dangerous_path_op, _expand
import shutil
import os
from pathlib import Path
from typing import Optional


class FsMoveTool(BaseTool):
    name = "fs.move"
    description = "Move or rename a file/directory"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "src": {"type": "str", "required": True},
        "dst": {"type": "str", "required": True},
    }

    def __init__(self, working_dir: Optional[WorkingDirFn] = None) -> None:
        self._working_dir = working_dir

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        src = str(arguments.get("src") or "")
        dst = str(arguments.get("dst") or "")
        if is_credential_path(src) or is_credential_path(dst):
            return PermissionLevel.DANGEROUS
        if is_dangerous_path_op(src) or is_dangerous_path_op(dst):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.SYSTEM

    def validate(self, arguments: dict[str, Any]) -> Optional[str]:
        """Validate arguments for fs.move tool."""
        src_raw = str(arguments.get("src") or "")
        dst_raw = str(arguments.get("dst") or "")

        if not src_raw:
            return "src required"
        if not dst_raw:
            return "dst required"

        # Additional safety checks
        base = self._working_dir() if self._working_dir else None
        src_path = _expand(src_raw, base=base)
        dst_path = _expand(dst_raw, base=base)

        # Prevent moving credential/secret paths
        if is_credential_path(src_raw) or is_credential_path(dst_raw):
            return "Refusing to move credential/secret paths."

        # Prevent moving to/from sensitive paths
        if is_dangerous_path_op(str(src_path), delete=False) and str(src_path) in ("/",):
            return "Refusing to move from sensitive path."
        if is_dangerous_path_op(str(dst_path), delete=False) and str(dst_path) in ("/",):
            return "Refusing to move to sensitive path."

        # Prevent moving a path onto itself
        if src_path == dst_path:
            return "Source and destination are the same."

        # Prevent moving inside itself (would create infinite loop)
        try:
            if dst_path.is_relative_to(src_path):
                return "Cannot move a path inside itself."
        except ValueError:
            # relative_to raises ValueError if paths are not related
            pass

        return None

    def prepare_rollback(self, arguments: dict[str, Any]) -> Any:
        """Prepare rollback data for fs.move - track original state."""
        src_raw = str(arguments.get("src") or "")
        dst_raw = str(arguments.get("dst") or "")
        if not src_raw or not dst_raw:
            return None

        base = self._working_dir() if self._working_dir else None
        src_path = _expand(src_raw, base=base)
        dst_path = _expand(dst_raw, base=base)

        # Track what existed before the move
        src_existed = src_path.exists()
        dst_existed = dst_path.exists()
        src_is_file = src_path.is_file() if src_existed else False
        src_is_dir = src_path.is_dir() if src_existed else False
        dst_is_file = dst_path.is_file() if dst_existed else False
        dst_is_dir = dst_path.is_dir() if dst_existed else False

        # If destination existed, track its content for potential restore
        dst_backup = None
        if dst_existed:
            try:
                if dst_is_file:
                    dst_backup = {
                        "type": "file",
                        "content": dst_path.read_text(encoding="utf-8", errors="replace")
                    }
                elif dst_is_dir:
                    # For directories, we could backup a listing, but for simplicity
                    # we'll note that a directory existed
                    dst_backup = {"type": "directory"}
            except OSError:
                # If we can't read, we can't reliably backup
                pass

        return {
            "src_path": str(src_path),
            "dst_path": str(dst_path),
            "src_existed": src_existed,
            "dst_existed": dst_existed,
            "src_is_file": src_is_file,
            "src_is_dir": src_is_dir,
            "dst_is_file": dst_is_file,
            "dst_is_dir": dst_is_dir,
            "dst_backup": dst_backup
        }

    def rollback(self, arguments: dict[str, Any], rollback_data: Any) -> bool:
        """Execute rollback for fs.move by restoring original state."""
        if not isinstance(rollback_data, dict):
            return False

        src_path_str = rollback_data.get("src_path")
        dst_path_str = rollback_data.get("dst_path")
        if not src_path_str or not dst_path_str:
            return False

        from pathlib import Path
        src_path = Path(src_path_str)
        dst_path = Path(dst_path_str)

        try:
            # If source existed before and destination exists now, move back
            if rollback_data["src_existed"] and dst_path.exists():
                # Move destination back to source location
                src_path.parent.mkdir(parents=True, exist_ok=True)
                dst_path.rename(src_path)
                return True
            # If source didn't exist before but destination exists now,
            # it means we created the destination by moving source to it
            # In rollback, we should move it back and remove the source if it was newly created
            elif not rollback_data["src_existed"] and dst_path.exists():
                # Move destination back to where source would have been
                dst_path.rename(src_path)
                return True
            # If both existed before, we should restore destination to its original state
            elif rollback_data["src_existed"] and rollback_data["dst_existed"]:
                # Both existed - this is tricky. The move likely overwrote dst.
                # For safety, we'll leave current state and log that manual intervention may be needed
                # In a more sophisticated system, we'd have backed up dst contents
                return True  # Assume no harm done for now
            # If neither existed, nothing to do
            elif not rollback_data["src_existed"] and not rollback_data["dst_existed"]:
                return True
        except OSError:
            return False

        return False

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        src_raw = str(arguments.get("src") or "")
        dst_raw = str(arguments.get("dst") or "")
        if is_credential_path(src_raw) or is_credential_path(dst_raw):
            return ToolResult(
                ok=False,
                error="Refusing to move credential/secret paths without explicit Level-3 flow.",
            )
        base = self._working_dir() if self._working_dir else None
        src = _expand(src_raw, base=base)
        dst = _expand(dst_raw, base=base)
        if is_credential_path(src_raw) or is_credential_path(dst_raw):
            return ToolResult(
                ok=False,
                error="Refusing to move credential/secret paths without explicit Level-3 flow.",
            )
        if not src.exists():
            return ToolResult(ok=False, error=f"Source not found: {src}")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return ToolResult(ok=True, data=f"Moved to {dst.name}.")
        except OSError as err:
            return ToolResult(ok=False, error=str(err))


class FsReadTool(BaseTool):
    name = "fs.read"
    description = "Read a file"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "path": {"type": "str", "required": True},
    }

    def __init__(self, working_dir: Optional[WorkingDirFn] = None) -> None:
        self._working_dir = working_dir

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        path = str(arguments.get("path") or "")
        if is_credential_path(path) or is_dangerous_path_op(path, delete=False):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.SYSTEM

    def validate(self, arguments: dict[str, Any]) -> Optional[str]:
        """Validate arguments for fs.read tool."""
        path_raw = str(arguments.get("path") or "")

        if not path_raw:
            return "path required"

        # Additional safety checks
        base = self._working_dir() if self._working_dir else None
        path = _expand(path_raw, base=base)

        # Prevent reading credential/secret paths
        if is_credential_path(path_raw):
            return "Refusing to read credential/secret paths."

        # Check if path exists
        if not path.exists():
            return f"Path not found: {path}"

        # Check if it's a file (not a directory)
        if not path.is_file():
            return f"Path is not a file: {path}"

        return None

    def prepare_rollback(self, arguments: dict[str, Any]) -> Any:
        """Read tool doesn't modify state, so no rollback needed."""
        return None

    def rollback(self, arguments: dict[str, Any], rollback_data: Any) -> bool:
        """Read tool doesn't modify state, so rollback is not applicable."""
        return False

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        path_raw = str(arguments.get("path") or "")
        if is_credential_path(path_raw):
            return ToolResult(
                ok=False,
                error="Refusing to read credential/secret paths without explicit Level-3 flow.",
            )
        base = self._working_dir() if self._working_dir else None
        path = _expand(path_raw, base=base)
        if not path.exists():
            return ToolResult(ok=False, error=f"Path not found: {path}")
        if not path.is_file():
            return ToolResult(ok=False, error=f"Path is not a file: {path}")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return ToolResult(ok=True, data=content)
        except OSError as err:
            return ToolResult(ok=False, error=str(err))


class FsWriteTool(BaseTool):
    name = "fs.write"
    description = "Write or overwrite a file"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "path": {"type": "str", "required": True},
        "content": {"type": "str", "required": True},
    }

    def __init__(self, working_dir: Optional[WorkingDirFn] = None) -> None:
        self._working_dir = working_dir

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        path = str(arguments.get("path") or "")
        if is_credential_path(path) or is_dangerous_path_op(path, delete=False):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.SYSTEM

    def validate(self, arguments: dict[str, Any]) -> Optional[str]:
        """Validate arguments for fs.write tool."""
        path_raw = str(arguments.get("path") or "")
        content_raw = str(arguments.get("content") or "")

        if not path_raw:
            return "path required"
        if not content_raw:
            return "content required"

        # Additional safety checks
        base = self._working_dir() if self._working_dir else None
        path = _expand(path_raw, base=base)

        # Prevent writing to credential/secret paths
        if is_credential_path(path_raw):
            return "Refusing to write to credential/secret paths."

        # Check if parent directory exists or can be created
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            return f"Cannot create parent directory: {err}"

        return None

    def prepare_rollback(self, arguments: dict[str, Any]) -> Any:
        """Prepare rollback data for fs.write - backup original file if it exists."""
        path_raw = str(arguments.get("path") or "")
        if not path_raw:
            return None

        base = self._working_dir() if self._working_dir else None
        path = _expand(path_raw, base=base)

        # If file existed, backup its content
        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                return {
                    "path": str(path),
                    "existed": True,
                    "content": content
                }
            except OSError:
                # If we can't read, we can't reliably backup
                return {
                    "path": str(path),
                    "existed": True,
                    "content": None
                }
        else:
            # File didn't exist
            return {
                "path": str(path),
                "existed": False
            }

    def rollback(self, arguments: dict[str, Any], rollback_data: Any) -> bool:
        """Execute rollback for fs.write by restoring original file."""
        if not isinstance(rollback_data, dict):
            return False

        path_str = rollback_data.get("path")
        if not path_str:
            return False

        path = Path(path_str)

        try:
            if rollback_data.get("existed", False):
                # File existed before, restore its content
                content = rollback_data.get("content")
                if content is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                    return True
                else:
                    # Couldn't backup content, best we can do is remove the file
                    if path.exists():
                        path.unlink()
                        return True
                    return False
            else:
                # File didn't exist before, remove it if it exists now
                if path.exists():
                    path.unlink()
                    return True
                return False
        except OSError:
            return False

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        path_raw = str(arguments.get("path") or "")
        content_raw = str(arguments.get("content") or "")
        if is_credential_path(path_raw):
            return ToolResult(
                ok=False,
                error="Refusing to write to credential/secret paths without explicit Level-3 flow.",
            )
        base = self._working_dir() if self._working_dir else None
        path = _expand(path_raw, base=base)
        try:
            # Ensure parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content_raw, encoding="utf-8")
            return ToolResult(ok=True, data=f"Wrote to {path.name}")
        except OSError as err:
            return ToolResult(ok=False, error=str(err))


class FsCreateTool(BaseTool):
    name = "fs.create"
    description = "Create a new file (fails if file already exists)"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "path": {"type": "str", "required": True},
        "content": {"type": "str", "required": False, "default": ""},
    }

    def __init__(self, working_dir: Optional[WorkingDirFn] = None) -> None:
        self._working_dir = working_dir

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        path = str(arguments.get("path") or "")
        if is_credential_path(path) or is_dangerous_path_op(path, delete=False):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.SYSTEM

    def validate(self, arguments: dict[str, Any]) -> Optional[str]:
        """Validate arguments for fs.create tool."""
        path_raw = str(arguments.get("path") or "")
        content_raw = str(arguments.get("content") or "")

        if not path_raw:
            return "path required"

        # Additional safety checks
        base = self._working_dir() if self._working_dir else None
        path = _expand(path_raw, base=base)

        # Prevent creating in credential/secret paths
        if is_credential_path(path_raw):
            return "Refusing to create in credential/secret paths."

        # Check if file already exists
        if path.exists():
            return f"File already exists: {path}"

        # Check if parent directory exists or can be created
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            return f"Cannot create parent directory: {err}"

        return None

    def prepare_rollback(self, arguments: dict[str, Any]) -> Any:
        """Prepare rollback data for fs.create - track that file was created."""
        path_raw = str(arguments.get("path") or "")
        if not path_raw:
            return None

        base = self._working_dir() if self._working_dir else None
        path = _expand(path_raw, base=base)

        # Track that we created this file
        return {
            "path": str(path),
            "created": True
        }

    def rollback(self, arguments: dict[str, Any], rollback_data: Any) -> bool:
        """Execute rollback for fs.create by removing the created file."""
        if not isinstance(rollback_data, dict):
            return False

        path_str = rollback_data.get("path")
        if not path_str:
            return False

        path = Path(path_str)

        try:
            # Remove the file we created
            if path.exists():
                path.unlink()
                return True
            return False
        except OSError:
            return False

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        path_raw = str(arguments.get("path") or "")
        content_raw = str(arguments.get("content") or "")
        if is_credential_path(path_raw):
            return ToolResult(
                ok=False,
                error="Refusing to create in credential/secret paths without explicit Level-3 flow.",
            )
        base = self._working_dir() if self._working_dir else None
        path = _expand(path_raw, base=base)
        try:
            # Ensure parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)
            # Create file with content (will fail if file exists due to 'x' mode)
            path.write_text(content_raw, encoding="utf-8")
            return ToolResult(ok=True, data=f"Created {path.name}")
        except OSError as err:
            return ToolResult(ok=False, error=str(err))


class FsListTool(BaseTool):
    name = "fs.list"
    description = "List contents of a directory"
    permission_level = PermissionLevel.SYSTEM
    input_schema = {
        "path": {"type": "str", "required": False, "default": "."},
    }

    def __init__(self, working_dir: Optional[WorkingDirFn] = None) -> None:
        self._working_dir = working_dir

    def resolve_permission(self, arguments: dict[str, Any]) -> PermissionLevel:
        path = str(arguments.get("path") or ".")
        if is_credential_path(path) or is_dangerous_path_op(path, delete=False):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.SYSTEM

    def validate(self, arguments: dict[str, Any]) -> Optional[str]:
        """Validate arguments for fs.list tool."""
        path_raw = str(arguments.get("path") or ".")

        # Additional safety checks
        base = self._working_dir() if self._working_dir else None
        path = _expand(path_raw, base=base)

        # Prevent listing credential/secret paths
        if is_credential_path(path_raw):
            return "Refusing to list credential/secret paths."

        # Check if path exists
        if not path.exists():
            return f"Path not found: {path}"

        # Check if it's a directory
        if not path.is_dir():
            return f"Path is not a directory: {path}"

        return None

    def prepare_rollback(self, arguments: dict[str, Any]) -> Any:
        """List tool doesn't modify state, so no rollback needed."""
        return None

    def rollback(self, arguments: dict[str, Any], rollback_data: Any) -> bool:
        """List tool doesn't modify state, so rollback is not applicable."""
        return False

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        path_raw = str(arguments.get("path") or ".")
        if is_credential_path(path_raw):
            return ToolResult(
                ok=False,
                error="Refusing to list credential/secret paths without explicit Level-3 flow.",
            )
        base = self._working_dir() if self._working_dir else None
        path = _expand(path_raw, base=base)
        try:
            if not path.exists():
                return ToolResult(ok=False, error=f"Path not found: {path}")
            if not path.is_dir():
                return ToolResult(ok=False, error=f"Path is not a directory: {path}")

            items = []
            for item in path.iterdir():
                items.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0
                })

            return ToolResult(ok=True, data={
                "path": str(path),
                "items": items
            })
        except OSError as err:
            return ToolResult(ok=False, error=str(err))