import io
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from octopulse import core  # noqa: E402

_cli_spec = importlib.util.spec_from_file_location("octopulse_cli", REPO_ROOT / "tools" / "octopulse.py")
assert _cli_spec and _cli_spec.loader
cli = importlib.util.module_from_spec(_cli_spec)
_cli_spec.loader.exec_module(cli)


def valid_marker(name="Example"):
    return {
        "schema_version": 2,
        "name": name,
        "last_updated": "2026-07-11T10:00:00+08:00",
        "phase": "implementation",
        "health": "active",
        "goal": "Keep progress current.",
        "summary": "The marker is valid.",
        "next_action": "Run tests.",
        "verification": {"status": "passed", "last_command": "python -m unittest", "last_verified_at": "2026-07-11T10:00:00+08:00"},
        "attention": [],
    }


class OctoPulseV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "octopulse-home"
        self.environment = patch.dict(os.environ, {"OCTOPULSE_HOME": str(self.home)}, clear=False)
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def make_git_project(self, name="Project"):
        project = self.root / name
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        return project

    def test_marker_states_and_schema_are_strict(self):
        marker = self.root / ".otcopulse"
        marker.touch()
        self.assertEqual(core.inspect_marker(marker)["state"], "uninitialized")

        core.write_json(marker, valid_marker())
        self.assertEqual(core.inspect_marker(marker)["state"], "valid")

        invalid = valid_marker()
        invalid["legacy"] = True
        core.write_json(marker, invalid)
        inspected = core.inspect_marker(marker)
        self.assertEqual(inspected["state"], "invalid")
        self.assertIn("unknown field `legacy`", inspected["errors"][0])

        marker.write_bytes(b"x" * (core.MAX_MARKER_BYTES + 1))
        self.assertEqual(core.inspect_marker(marker)["state"], "invalid")

    def test_discovery_skips_dependency_directories_and_non_root_marker_is_invalid(self):
        project = self.make_git_project()
        core.write_json(project / ".otcopulse", valid_marker("Root"))
        nested = project / "node_modules" / "ignored"
        nested.mkdir(parents=True)
        core.write_json(nested / ".otcopulse", valid_marker("Ignored"))
        misplaced = project / "src"
        misplaced.mkdir()
        core.write_json(misplaced / ".otcopulse", valid_marker("Misplaced"))
        core.add_root(self.root)

        entries, reads, _ = core.scan_projects()
        self.assertEqual(len(entries), 2)
        self.assertNotIn(str(nested / ".otcopulse"), reads)
        by_marker = {Path(entry["marker"]).resolve(): entry for entry in entries}
        self.assertEqual(by_marker[(project / ".otcopulse").resolve()]["state"], "valid")
        self.assertEqual(by_marker[(misplaced / ".otcopulse").resolve()]["state"], "invalid")

    def test_report_cache_skips_rewrite_and_explain_reports_reads(self):
        project = self.make_git_project()
        core.write_json(project / ".otcopulse", valid_marker())
        core.add_root(project)
        output = self.root / "reports"

        first = io.StringIO()
        with redirect_stdout(first):
            self.assertEqual(cli.main(["report", "--output", str(output), "--explain"]), 0)
        first_result = json.loads(first.getvalue())
        self.assertFalse(first_result["cached"])
        self.assertEqual(first_result["marker_reads"], [str((project / ".otcopulse").resolve())])
        report = output / "latest.md"
        initial_content = report.read_text(encoding="utf-8")

        second = io.StringIO()
        with redirect_stdout(second):
            self.assertEqual(cli.main(["report", "--output", str(output), "--explain"]), 0)
        second_result = json.loads(second.getvalue())
        self.assertTrue(second_result["cached"])
        self.assertEqual(report.read_text(encoding="utf-8"), initial_content)

    def test_init_requires_confirmation_and_guidance_is_idempotent(self):
        project = self.make_git_project()
        previous = Path.cwd()
        try:
            os.chdir(project)
            self.assertEqual(cli.main(["init"]), 2)
            self.assertEqual(cli.main(["init", "--yes", "--agent", "codex"]), 0)
            guidance = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(guidance.count("<!-- octopulse:start -->"), 1)
            self.assertEqual(cli.main(["init", "--yes", "--force", "--agent", "codex"]), 0)
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8").count("<!-- octopulse:start -->"), 1)
        finally:
            os.chdir(previous)

    def test_archive_creates_stale_marker_without_touching_legacy_files(self):
        project = self.make_git_project()
        legacy = project / ".ai" / "status.json"
        legacy.parent.mkdir()
        legacy.write_text("legacy status must remain untouched", encoding="utf-8")
        document = project / "PROJECT_STATUS.md"
        document.write_text("legacy document must remain untouched", encoding="utf-8")
        previous = Path.cwd()
        try:
            os.chdir(project)
            self.assertEqual(cli.main(["archive", "--yes", "--reason", "Superseded by a new platform."]), 0)
            marker = core.inspect_marker(project / ".otcopulse")
            self.assertEqual(marker["state"], "valid")
            self.assertEqual(marker["payload"]["phase"], "paused")
            self.assertEqual(marker["payload"]["health"], "stale")
            self.assertEqual(marker["payload"]["summary"], "Superseded by a new platform.")
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy status must remain untouched")
            self.assertEqual(document.read_text(encoding="utf-8"), "legacy document must remain untouched")
        finally:
            os.chdir(previous)

    def test_release_archive_contains_only_v2_runtime_assets(self):
        output = self.root / "release"
        subprocess.run(["sh", str(REPO_ROOT / "scripts" / "package-release.sh"), str(output)], cwd=REPO_ROOT, check=True)
        with tarfile.open(output / "octopulse.tar.gz", "r:gz") as archive:
            names = archive.getnames()
        self.assertIn("octopulse/core.py", names)
        self.assertIn("tools/octopulse.py", names)
        self.assertIn("skills/octopulse/SKILL.md", names)
        self.assertIn("schemas/otcopulse.schema.json", names)
        self.assertFalse(any(name.startswith("tools/scan_projects.py") for name in names))
        self.assertFalse(any(name.startswith("tools/validate_status.py") for name in names))


if __name__ == "__main__":
    unittest.main()
