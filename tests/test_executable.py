import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import workspace as app


class ExecutableTests(unittest.TestCase):
    def test_restricted_path_falls_back_to_user_install(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=True), \
                    patch.object(Path, "home", return_value=home):
                self.assertEqual(app.resolve_codex(), "codex")
                for directory in (home / "bin", home / ".local/bin"):
                    directory.mkdir(parents=True)
                    executable = directory / "codex"
                    executable.write_text("#!/bin/sh\nexit 0\n")
                    self.assertEqual(app.resolve_codex(), "codex" if directory == home / "bin" else str(home / "bin/codex"))
                    executable.chmod(0o755)
                    self.assertEqual(app.resolve_codex(), str(executable))
                # PATH takes precedence over fallback directories.
                os.environ["PATH"] = str(home / "bin")
                self.assertEqual(app.resolve_codex(), str(home / "bin/codex"))

    def test_explicit_override_is_not_silently_replaced(self):
        for value in ("custom-codex", "/missing/codex"):
            with self.subTest(value=value), patch.dict(os.environ, {"CODEX_WORKSPACE_CODEX": value}):
                self.assertEqual(app.resolve_codex(), value)
