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

from octopulse import core, hooks, reports  # noqa: E402

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
        subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(project), "config", "user.name", "OctoPulse Test"], check=True)
        return project

    def commit(self, project: Path, name: str, subject: str):
        (project / name).write_text(subject, encoding="utf-8")
        subprocess.run(["git", "-C", str(project), "add", name], check=True)
        subprocess.run(["git", "-C", str(project), "commit", "-qm", subject], check=True)

    def run_hook(self, arguments: list[str], payload: dict):
        output = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), redirect_stdout(output):
            self.assertEqual(cli.main(arguments), 0)
        return output.getvalue()

    def test_marker_states_and_schema_are_strict(self):
        marker = self.root / ".octopulse"
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

    def test_legacy_marker_is_ignored_until_explicit_migration(self):
        project = self.make_git_project()
        legacy = project / core.LEGACY_MARKER_NAME
        legacy.write_bytes(b'{"invalid":true}\n')
        core.add_root(project)
        self.assertEqual(core.context_for(project)["state"], "missing")
        self.assertEqual(core.scan_projects()[0], [])

        previous = Path.cwd()
        try:
            os.chdir(project)
            self.assertEqual(cli.main(["migrate-marker"]), 2)
            for content in (b"", json.dumps(valid_marker()).encode("utf-8"), b"not valid JSON"):
                legacy.write_bytes(content)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["migrate-marker", "--yes"]), 0)
                current = project / core.MARKER_NAME
                self.assertEqual(current.read_bytes(), content)
                self.assertFalse(legacy.exists())
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["migrate-marker", "--yes"]), 0)
                current.unlink()

            legacy.write_bytes(b"legacy")
            (project / core.MARKER_NAME).write_bytes(b"current")
            self.assertEqual(cli.main(["migrate-marker", "--yes"]), 1)
            self.assertEqual(legacy.read_bytes(), b"legacy")
            self.assertEqual((project / core.MARKER_NAME).read_bytes(), b"current")
        finally:
            os.chdir(previous)

    def test_discovery_skips_dependency_directories_and_non_root_marker_is_invalid(self):
        project = self.make_git_project()
        core.write_json(project / ".octopulse", valid_marker("Root"))
        nested = project / "node_modules" / "ignored"
        nested.mkdir(parents=True)
        core.write_json(nested / ".octopulse", valid_marker("Ignored"))
        misplaced = project / "src"
        misplaced.mkdir()
        core.write_json(misplaced / ".octopulse", valid_marker("Misplaced"))
        core.add_root(self.root)

        entries, reads, _ = core.scan_projects()
        self.assertEqual(len(entries), 2)
        self.assertNotIn(str(nested / ".octopulse"), reads)
        by_marker = {Path(entry["marker"]).resolve(): entry for entry in entries}
        self.assertEqual(by_marker[(project / ".octopulse").resolve()]["state"], "valid")
        self.assertEqual(by_marker[(misplaced / ".octopulse").resolve()]["state"], "invalid")

    def test_report_alias_refreshes_project_snapshots_incrementally(self):
        project = self.make_git_project()
        core.write_json(project / ".octopulse", valid_marker())
        core.add_root(project)
        output = self.root / "reports"

        first = io.StringIO()
        with redirect_stdout(first):
            self.assertEqual(cli.main(["report", "--output", str(output), "--explain"]), 0)
        first_result = json.loads(first.getvalue())
        self.assertEqual(first_result["refreshed_projects"], [str(project.resolve())])
        report = output / "latest.md"
        initial_content = report.read_text(encoding="utf-8")

        second = io.StringIO()
        with redirect_stdout(second):
            self.assertEqual(cli.main(["report", "--output", str(output), "--explain"]), 0)
        second_result = json.loads(second.getvalue())
        self.assertEqual(second_result["refreshed_projects"], [])
        self.assertTrue(second_result["cached"])
        self.assertEqual(second_result["written"], [])
        self.assertEqual(report.read_text(encoding="utf-8"), initial_content)

    def test_project_snapshot_collects_git_legacy_activity_and_report_details(self):
        project = self.make_git_project()
        core.write_json(project / ".octopulse", valid_marker("Detailed"))
        self.commit(project, "one.txt", "Add transport guard")
        self.commit(project, "two.txt", "Verify secure path")
        legacy_path = project / ".ai" / "status.json"
        legacy_path.parent.mkdir()
        core.write_json(legacy_path, {"phase": "maintenance", "health": "stable", "current_goal": "Old goal", "latest_summary": "Old summary", "next_action": "Old next", "verification": {"status": "passed"}})
        reports.record_activity(project, "codex", "start")
        reports.record_activity(project, "claude", "finish", "updated")
        reports.record_activity(project, "grok", "finish", "unchanged")

        snapshot, cached = reports.refresh_project_report(project, history=10)
        self.assertFalse(cached)
        self.assertEqual([entry["subject"] for entry in snapshot["history"]], ["Verify secure path", "Add transport guard"])
        self.assertEqual(snapshot["legacy_context"]["goal"], "Old goal")
        self.assertEqual({entry["tool"] for entry in snapshot["activity"]["tools"]}, {"codex", "claude", "grok"})
        self.assertEqual({entry["tool"] for entry in snapshot["activity"]["recent_events"]}, {"codex", "claude", "grok"})
        self.assertTrue((project / ".git" / "info" / "exclude").read_text(encoding="utf-8").find("/.octopulse-reports/") >= 0)
        markdown = (reports.report_dir(project) / "latest.md").read_text(encoding="utf-8")
        self.assertIn("Recent commits", reports.project_markdown(snapshot, "en"))
        self.assertIn("Last updated", reports.project_markdown(snapshot, "en"))
        self.assertIn("Verify secure path", markdown)
        _, english_cached = reports.refresh_project_report(project, history=10, language="en")
        self.assertFalse(english_cached)
        self.assertIn("# OctoPulse Project Report", (reports.report_dir(project) / "latest.md").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8"))["current_goal"], "Old goal")

    def test_project_and_portfolio_commands_handle_snapshots_and_stale_reports(self):
        project = self.make_git_project()
        core.write_json(project / ".octopulse", valid_marker("CLI Project"))
        core.add_root(project)
        project_output = io.StringIO()
        with redirect_stdout(project_output):
            self.assertEqual(cli.main(["project", "report", "--project", str(project), "--lang", "en"]), 0)
        self.assertTrue((reports.report_dir(project) / "snapshot.json").is_file())

        snapshot_path = reports.snapshot_path(project)
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["generated_at"] = "2020-01-01T00:00:00+00:00"
        core.write_json(snapshot_path, snapshot)
        portfolio, refreshed = reports.collect_portfolio(refresh="never")
        self.assertEqual(refreshed, [])
        self.assertIn("snapshot_stale", portfolio["projects"][0]["signals"])

    def test_portfolio_html_has_navigation_and_localized_interface(self):
        project = self.make_git_project()
        core.write_json(project / ".octopulse", valid_marker("Portfolio Project"))
        core.add_root(project)
        portfolio, refreshed = reports.collect_portfolio(refresh="auto", language="zh-TW")
        self.assertEqual(refreshed, [str(project.resolve())])
        html = reports.portfolio_html(portfolio)
        self.assertIn("location.hash", html)
        self.assertIn("lang", html)
        self.assertIn("Portfolio Project", html)
        self.assertIn("projectKey", html)
        self.assertIn("recent_events", html)
        self.assertIn("prefers-reduced-motion", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("<pre>", html)
        self.assertIn("detail-grid", reports.project_html(portfolio["projects"][0], "en"))
        portfolio_again, refreshed_again = reports.collect_portfolio(refresh="auto", language="zh-TW")
        self.assertEqual(refreshed_again, [])
        self.assertEqual(portfolio_again["projects"][0]["project"]["name"], "Portfolio Project")

    def test_codex_session_start_hook_is_gated_and_never_echoes_prompt(self):
        project = self.make_git_project()
        core.write_json(project / ".octopulse", valid_marker("Hook Project"))
        core.add_root(project)
        output = self.run_hook(
            ["hook", "codex-session-start"],
            {"hook_event_name": "SessionStart", "cwd": str(project), "prompt": "secret prompt must not leak"},
        )
        response = json.loads(output)
        self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("OctoPulse", response["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("secret prompt", output)

        marker = valid_marker("Paused")
        marker["phase"] = "paused"
        core.write_json(project / ".octopulse", marker)
        self.assertEqual(self.run_hook(["hook", "codex-session-start"], {"hook_event_name": "SessionStart", "cwd": str(project)}), "")
        self.assertEqual(self.run_hook(["hook", "codex-session-start"], {"hook_event_name": "SessionStart", "cwd": str(self.root)}), "")

        unregistered = self.make_git_project("Unregistered")
        core.write_json(unregistered / ".octopulse", valid_marker("Unregistered"))
        self.assertEqual(self.run_hook(["hook", "codex-session-start"], {"hook_event_name": "SessionStart", "cwd": str(unregistered)}), "")
        (unregistered / ".octopulse").write_bytes(b"not JSON")
        self.assertEqual(self.run_hook(["hook", "codex-session-start"], {"hook_event_name": "SessionStart", "cwd": str(unregistered)}), "")
        (unregistered / ".octopulse").write_text("", encoding="utf-8")
        self.assertEqual(self.run_hook(["hook", "codex-session-start"], {"hook_event_name": "SessionStart", "cwd": str(unregistered)}), "")

    def test_codex_stop_hook_refreshes_only_changed_managed_projects(self):
        project = self.make_git_project()
        core.write_json(project / ".octopulse", valid_marker("Stop Project"))
        core.add_root(project)
        payload = {"hook_event_name": "Stop", "cwd": str(project)}
        self.assertEqual(self.run_hook(["hook", "codex-stop"], payload), "")
        snapshot = reports.snapshot_path(project)
        portfolio = core.default_report_dir() / "projects.json"
        self.assertTrue(snapshot.exists())
        self.assertTrue(portfolio.exists())
        snapshot_mtime = snapshot.stat().st_mtime_ns
        portfolio_mtime = portfolio.stat().st_mtime_ns
        for _ in range(20):
            self.assertEqual(self.run_hook(["hook", "codex-stop"], payload), "")
        self.assertEqual(snapshot.stat().st_mtime_ns, snapshot_mtime)
        self.assertEqual(portfolio.stat().st_mtime_ns, portfolio_mtime)

        with reports.project_hook_lock(project) as first_lock:
            self.assertTrue(first_lock)
            with reports.project_hook_lock(project) as second_lock:
                self.assertFalse(second_lock)

        marker = valid_marker("Archived")
        marker["phase"] = "paused"
        marker["health"] = "stale"
        core.write_json(project / ".octopulse", marker)
        self.assertEqual(self.run_hook(["hook", "codex-stop"], payload), "")
        self.assertEqual(snapshot.stat().st_mtime_ns, snapshot_mtime)

    def test_grok_stop_hook_is_gated_and_never_echoes_prompt(self):
        project = self.make_git_project()
        core.write_json(project / ".octopulse", valid_marker("Grok Project"))
        core.add_root(project)
        payload = {"hookEventName": "Stop", "cwd": str(project), "prompt": "secret prompt must not leak"}
        self.assertEqual(self.run_hook(["hook", "grok-stop"], payload), "")
        snapshot = reports.snapshot_path(project)
        portfolio = core.default_report_dir() / "projects.json"
        self.assertTrue(snapshot.exists())
        self.assertTrue(portfolio.exists())
        snapshot_mtime = snapshot.stat().st_mtime_ns
        portfolio_mtime = portfolio.stat().st_mtime_ns
        self.assertEqual(self.run_hook(["hook", "grok-stop"], payload), "")
        self.assertEqual(snapshot.stat().st_mtime_ns, snapshot_mtime)
        self.assertEqual(portfolio.stat().st_mtime_ns, portfolio_mtime)

        marker = valid_marker("Archived")
        marker["phase"] = "paused"
        marker["health"] = "stale"
        core.write_json(project / ".octopulse", marker)
        self.assertEqual(self.run_hook(["hook", "grok-stop"], payload), "")
        self.assertEqual(snapshot.stat().st_mtime_ns, snapshot_mtime)
        self.assertEqual(self.run_hook(["hook", "grok-stop"], {"hookEventName": "Stop", "cwd": str(self.root)}), "")

    def test_grok_hook_file_is_managed_without_touching_other_files(self):
        hooks_dir = self.root / "grok" / "hooks"
        hooks_dir.mkdir(parents=True)
        other = hooks_dir / "other.json"
        other.write_text('{"hooks":{"Stop":[]}}\n', encoding="utf-8")
        hooks_file = hooks_dir / "octopulse.json"
        result = hooks.install_grok_hooks(hooks_file, "/opt/octopulse")
        self.assertTrue(result["changed"])
        managed = json.loads(hooks_file.read_text(encoding="utf-8"))
        self.assertEqual(managed["hooks"]["Stop"][0]["hooks"][0]["command"], "/opt/octopulse hook grok-stop")
        self.assertFalse(hooks.install_grok_hooks(hooks_file, "/opt/octopulse")["changed"])
        self.assertEqual(other.read_text(encoding="utf-8"), '{"hooks":{"Stop":[]}}\n')
        self.assertTrue(hooks.remove_grok_hooks(hooks_file)["removed"])
        self.assertFalse(hooks_file.exists())
        self.assertTrue(other.exists())
        hooks_file.write_text('{"hooks":{"Stop":[]}}\n', encoding="utf-8")
        self.assertFalse(hooks.remove_grok_hooks(hooks_file)["removed"])
        self.assertTrue(hooks_file.exists())

    def test_grok_activity_and_guidance_are_supported(self):
        project = self.make_git_project()
        previous = Path.cwd()
        try:
            os.chdir(project)
            self.assertEqual(cli.main(["init", "--yes", "--agent", "grok"]), 0)
            self.assertTrue((project / "AGENTS.md").is_file())
            self.assertEqual(cli.main(["activity", "start", "--tool", "grok"]), 0)
        finally:
            os.chdir(previous)

    def test_installer_auto_adds_one_shared_skill_and_grok_hook(self):
        release = self.root / "release"
        subprocess.run(["sh", str(REPO_ROOT / "scripts" / "package-release.sh"), str(release)], cwd=REPO_ROOT, check=True)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake_curl = bin_dir / "curl"
        fake_curl.write_text(
            "#!/bin/sh\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  if [ \"$1\" = \"-o\" ]; then output=\"$2\"; shift 2; continue; fi\n"
            "  case \"$1\" in *octopulse.sha256) source=\"$OCTOPULSE_TEST_CHECKSUM\" ;; *octopulse.tar.gz) source=\"$OCTOPULSE_TEST_ARCHIVE\" ;; esac\n"
            "  shift\n"
            "done\n"
            "cp \"$source\" \"$output\"\n",
            encoding="utf-8",
        )
        fake_curl.chmod(0o755)
        home = self.root / "agent-home"
        (home / ".codex").mkdir(parents=True)
        (home / ".grok" / "hooks").mkdir(parents=True)
        other_hook = home / ".grok" / "hooks" / "other.json"
        other_hook.write_text('{"hooks":{"Stop":[]}}\n', encoding="utf-8")
        environment = os.environ | {
            "HOME": str(home),
            "OCTOPULSE_HOME": str(self.root / "installed-runtime"),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "OCTOPULSE_TEST_ARCHIVE": str(release / "octopulse.tar.gz"),
            "OCTOPULSE_TEST_CHECKSUM": str(release / "octopulse.sha256"),
        }
        subprocess.run(["sh", str(REPO_ROOT / "install.sh"), "--agent", "auto"], cwd=REPO_ROOT, env=environment, check=True)
        self.assertTrue((home / ".agents" / "skills" / "octopulse" / "SKILL.md").is_file())
        self.assertFalse((home / ".grok" / "skills" / "octopulse").exists())
        grok_hook = json.loads((home / ".grok" / "hooks" / "octopulse.json").read_text(encoding="utf-8"))
        self.assertIn("hook grok-stop", grok_hook["hooks"]["Stop"][0]["hooks"][0]["command"])
        self.assertTrue((home / ".codex" / "hooks.json").is_file())
        self.assertEqual(other_hook.read_text(encoding="utf-8"), '{"hooks":{"Stop":[]}}\n')
        subprocess.run(["sh", str(REPO_ROOT / "install.sh"), "--agent", "grok", "--remove-grok-hooks"], cwd=REPO_ROOT, env=environment, check=True)
        self.assertFalse((home / ".grok" / "hooks" / "octopulse.json").exists())
        self.assertTrue(other_hook.exists())

    def test_codex_hook_config_migrates_v1_without_touching_other_handlers(self):
        hooks_file = self.root / "codex" / "hooks.json"
        hooks_file.parent.mkdir()
        hooks_file.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {
                                "hooks": [
                                    {"type": "command", "command": "python /old/octopulse_codex_hook.py"},
                                    {"type": "command", "command": "python /other/keep.py"},
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        result = hooks.install_codex_hooks(hooks_file, "/opt/octopulse")
        self.assertEqual(result["removed_v1_handlers"], 1)
        self.assertTrue(Path(result["backup"]).is_file())
        migrated = json.loads(hooks_file.read_text(encoding="utf-8"))
        handlers = migrated["hooks"]["UserPromptSubmit"][0]["hooks"]
        self.assertEqual(handlers, [{"type": "command", "command": "python /other/keep.py"}])
        self.assertEqual(len(migrated["hooks"]["SessionStart"]), 1)
        self.assertEqual(len(migrated["hooks"]["Stop"]), 1)
        hooks.install_codex_hooks(hooks_file, "/opt/octopulse")
        rerun = json.loads(hooks_file.read_text(encoding="utf-8"))
        self.assertEqual(len(rerun["hooks"]["SessionStart"]), 1)
        self.assertEqual(len(rerun["hooks"]["Stop"]), 1)
        removed = hooks.remove_codex_hooks(hooks_file)
        self.assertEqual(removed["removed_v2_handlers"], 2)
        self.assertNotIn("SessionStart", json.loads(hooks_file.read_text(encoding="utf-8"))["hooks"])

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
            marker = core.inspect_marker(project / ".octopulse")
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
        self.assertIn("octopulse/reports.py", names)
        self.assertIn("octopulse/hooks.py", names)
        self.assertIn("tools/octopulse.py", names)
        self.assertIn("skills/octopulse/SKILL.md", names)
        self.assertIn("schemas/octopulse.schema.json", names)
        self.assertFalse(any(name.startswith("tools/scan_projects.py") for name in names))
        self.assertFalse(any(name.startswith("tools/validate_status.py") for name in names))
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))


if __name__ == "__main__":
    unittest.main()
