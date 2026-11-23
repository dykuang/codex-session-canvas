"""Release asset smoke: build in a disposable directory and inspect archive contents."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile


class ReleaseArchiveTest(unittest.TestCase):
    def test_versioned_installable_archive_contains_linked_modules(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="v05-archive-test-") as tmp:
            output = Path(tmp) / "codex-session-canvas-v0.5.0.zip"
            result = subprocess.run(
                [sys.executable, str(root / "scripts" / "build_release.py"),
                 "--output", str(output)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            with ZipFile(output) as package:
                names = set(package.namelist())
                expected = {"install_skill.py", "SKILL.md", "canvas.py",
                            "linked_context.py", "linked_refresh.py",
                            "web/context.js", "docs/releases/v0.5.0.md"}
                for name in expected:
                    self.assertIn("codex-session-canvas/" + name, names)
                self.assertFalse(any("/.git/" in name or "__pycache__" in name
                                     or name.endswith(".pyc") for name in names))
                self.assertIsNone(package.testzip())
            self.assertTrue(output.is_file())
        self.assertFalse(output.exists(), "Release ZIP fixture was not cleaned up")


if __name__ == "__main__":
    unittest.main()
