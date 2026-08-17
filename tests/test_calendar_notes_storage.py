"""N-11 calendar/notes tools + N-12 storage backend factory."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.app import JarvisOS
from core.command_router import CommandRouter
from storage.backend import backend_kind, open_backend, open_sqlite
from tools.calendar_notes import CalendarNotesStore


class CalendarNotesToolTests(unittest.TestCase):
    def test_create_list_search_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/cn.db"}},
                root=Path(tmp),
            )
            names = os_core.tools.list_names()
            self.assertIn("notes.create", names)
            self.assertIn("calendar.today", names)

            speech = os_core.try_handle_command("add note buy milk")
            self.assertIsNotNone(speech)
            self.assertIn("Note #", speech or "")

            listed = os_core.try_handle_command("list notes")
            self.assertIn("milk", (listed or "").lower())

            found = os_core.try_handle_command("search notes milk")
            self.assertIn("milk", (found or "").lower())

            ev = os_core.try_handle_command("add event Team sync tomorrow 10:00")
            self.assertIsNotNone(ev)
            self.assertIn("Event #", ev or "")

            today = os_core.try_handle_command("calendar today")
            self.assertIsNotNone(today)
            os_core.close()

    def test_router_does_not_steal_open_notes(self) -> None:
        router = CommandRouter()
        match = router.route("open notes")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.request.tool_name, "system.open_app")


class StorageBackendFactoryTests(unittest.TestCase):
    def test_default_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.db"
            db = open_backend({"db_path": str(path)})
            self.assertEqual(backend_kind(db), "sqlite")
            db.migrate()
            store = CalendarNotesStore(db)
            nid = store.create_note("hello")
            self.assertGreater(nid, 0)
            db.close()

    def test_postgres_requires_dsn(self) -> None:
        with self.assertRaises(ValueError):
            open_backend({"storage": {"backend": "postgres"}})

    def test_postgres_import_error_without_psycopg(self) -> None:
        # If psycopg is installed this still constructs — mock ImportError path
        import storage.postgres as pg

        real_init = pg.PostgresDatabase.__init__

        def boom(self, dsn, *, display_path=None):  # type: ignore[no-untyped-def]
            raise ImportError("psycopg missing")

        pg.PostgresDatabase.__init__ = boom  # type: ignore[method-assign]
        try:
            with self.assertRaises(ImportError):
                open_backend(
                    {"storage": {"backend": "postgres", "dsn": "postgresql://x"}}
                )
        finally:
            pg.PostgresDatabase.__init__ = real_init  # type: ignore[method-assign]

    def test_open_sqlite_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_sqlite(Path(tmp) / "a.db")
            self.assertTrue(hasattr(db, "migrate"))
            db.close()

    def test_jarvis_os_db_under_root_not_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os_core = JarvisOS(
                {"jarvis2": {"db_path": "data/isolated.db"}},
                root=root,
            )
            try:
                self.assertTrue(str(os_core.db.path).startswith(str(root.resolve())))
                self.assertTrue((root / "data" / "isolated.db").exists())
            finally:
                os_core.close()


if __name__ == "__main__":
    unittest.main()
