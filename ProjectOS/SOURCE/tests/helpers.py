from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class TemporaryDirectoryMixin:
    def setUp(self) -> None:
        super().setUp()
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()
        super().tearDown()

    def open_database(self):
        from projectos.database import ProjectOSDatabase

        self.database = ProjectOSDatabase(self.temp_path / "projectos.db").initialize()
        self.addCleanup(self.database.close)
        return self.database
