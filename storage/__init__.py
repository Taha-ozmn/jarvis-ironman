"""storage package — DB abstraction seam (Phase 14)."""

from storage.backend import StorageBackend, backend_kind, open_sqlite

__all__ = ["StorageBackend", "backend_kind", "open_sqlite"]
