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
        "schema_version": 3,
        "name": name,
        "last_updated": "2026-07-11T10:00:00+08:00",
        "phase": "implementation",
        "health": "active",
        "goal": "Keep progress current.",
        "summary": "The marker is valid.",
        "next_action": "Run tests.",
        "verification": {"status": "passed", "last_command": "python -m unittest", "last_verified_at": "2026-07-11T10:00:00+08:00"},
        "attention": [],
        "handoff": None,
    }


def legacy_marker(name="Example"):
    marker = valid_marker(name)
    marker["schema_version"] = 2
    marker.pop("handoff")
    return marker


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

    def test_v2_marker_requires_explicit_schema_migration(self):
        project = self.make_git_project()
        marker = project / ".octopulse"
        core.write_json(marker, legacy_marker())
        self.assertEqual(core.context_for(project)["state"], "migration_required")
        self.assertEqual(cli.main(["migrate-schema", "--directory", str(project)]), 2)
        self.assertEqual(cli.main(["migrate-schema", "--directory", str(project), "--yes"]), 0)
        migrated = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(migrated["schema_version"], core.VERSION)
        self.assertIsNone(migrated["handoff"])
        self.assertEqual(core.inspect_marker(marker)["state"], "valid")
        self.assertEqual(cli.main(["migrate-schema", "--directory", str(project), "--yes"]), 0)

    def test_schema_migration_refuses_empty_invalid_and_unknown_markers(self):
        project = self.make_git_project()
        marker = project / ".octopulse"
        marker.touch()
        self.assertEqual(cli.main(["migrate-schema", "--directory", str(project), "--yes"]), 1)
        core.write_json(marker, {"schema_version": 99})
        self.assertEqual(cli.main(["migrate-schema", "--directory", str(project), "--yes"]), 1)

    def test_handoff_is_compact_and_only_points_to_existing_project_files(self):
        project = self.make_git_project()
        core.write_json(project / ".octopulse", valid_marker())
        core.add_root(project)
        self.commit(project, "tracked.py", "Add tracked file")
        (project / "tracked.py").write_text("changed", encoding="utf-8")
        (project / "untracked.py").write_text("new", encoding="utf-8")

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.main(["handoff", "create", "--project", str(project), "--tool", "codex", "--read-first", "tracked.py", "--decision", "Keep the existing API"]), 0)
        handoff = json.loads(output.getvalue())["handoff"]
        self.assertEqual(handoff["tool"], "codex")
        self.assertEqual(handoff["read_first"], ["tracked.py"])
        self.assertEqual(set(handoff["worktree_files"]), {"tracked.py", "untracked.py"})
        self.assertNotIn(".octopulse", handoff["worktree_files"])

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.main(["handoff", "show", "--project", str(project)]), 0)
        packet = json.loads(output.getvalue())
        self.assertEqual(packet["status"]["handoff"], handoff)
        self.assertTrue(packet["sync"]["marker_dirty"])
        self.assertIn("commit and push", packet["sync"]["warning"])
        snapshot, _ = reports.refresh_project_report(project, language="en")
        self.assertIn("Latest handoff", reports.project_markdown(snapshot, "en"))
        portfolio, _ = reports.collect_portfolio(refresh="auto", language="en")
        self.assertIn("Latest handoff", reports.portfolio_markdown(portfolio, "en"))
        self.assertIn("Latest handoff", reports.project_html(snapshot, "en"))
        self.assertEqual(cli.main(["handoff", "create", "--project", str(project), "--tool", "codex", "--read-first", "missing.py"]), 1)

    def test_handoff_schema_rejects_unsafe_paths_and_excessive_decisions(self):
        marker = valid_marker()
        marker["handoff"] = {
            "tool": "claude",
            "created_at": "2026-07-11T10:00:00+08:00",
            "commit": None,
            "worktree_files": ["../secret"],
            "read_first": [".git/config"],
            "decisions": ["x"] * 5,
        }
        errors = core.validate_marker_payload(marker)
        self.assertTrue(any("invalid relative path" in error for error in errors))
        self.assertTrue(any("decisions" in error for error in errors))

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
            for content in (b"", json.dumps(legacy_marker()).encode("utf-8"), b"not valid JSON"):
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
        self.assertEqual(snapshot["history"][0]["files"], ["two.txt"])
        self.assertEqual(snapshot["history"][0]["files_changed"], 1)
        self.assertEqual(snapshot["legacy_context"]["goal"], "Old goal")
        self.assertEqual({entry["tool"] for entry in snapshot["activity"]["tools"]}, {"codex", "claude", "grok"})
        self.assertEqual({entry["tool"] for entry in snapshot["activity"]["recent_events"]}, {"codex", "claude", "grok"})
        self.assertTrue((project / ".git" / "info" / "exclude").read_text(encoding="utf-8").find("/.octopulse-reports/") >= 0)
        markdown = (reports.report_dir(project) / "latest.md").read_text(encoding="utf-8")
        self.assertIn("Recently completed", reports.project_markdown(snapshot, "en"))
        self.assertIn("Last updated", reports.project_markdown(snapshot, "en"))
        self.assertIn("Verify secure path", markdown)
        _, english_cached = reports.refresh_project_report(project, history=10, language="en")
        self.assertFalse(english_cached)
        self.assertIn("# OctoPulse Project Report", (reports.report_dir(project) / "latest.md").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8"))["current_goal"], "Old goal")

    def test_project_page_leads_with_the_latest_commit(self):
        project = self.make_git_project("Reviewed")
        self.commit(project, "guide.md", "Show the v0.6.0 release in the guide's download step.")
        (project / "scratch.txt").write_text("draft", encoding="utf-8")
        marker = valid_marker("Reviewed")
        marker["goal"] = core.DEFAULT_GOAL
        marker["summary"] = core.DEFAULT_GOAL
        marker["next_action"] = core.DEFAULT_NEXT
        core.write_json(project / ".octopulse", marker)
        snapshot, _cached = reports.refresh_project_report(project, history=5)
        self.assertEqual(snapshot["git"]["worktree"]["files"], [{"path": "scratch.txt", "state": "untracked"}])
        markdown = reports.project_markdown(snapshot, "zh-TW")
        self.assertIn("最近做到哪", markdown)
        self.assertIn("Show the v0.6.0 release in the guide's download step.", markdown.split("最近完成了什麼", 1)[0])
        self.assertIn("untracked: scratch.txt", markdown)
        self.assertIn("尚未寫入目標", markdown)
        self.assertNotIn(core.DEFAULT_GOAL, markdown)
        html = reports.project_html(snapshot, "zh-TW")
        self.assertIn("h.decisions.join('\\n')", html)
        self.assertNotIn("join('\n", html)
        script = html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
        runner = self.root / "render-report.js"
        runner.write_text(
            "const script = process.argv[2];\n"
            "const elements = {};\n"
            "function el(id){return elements[id] || (elements[id] = {id, textContent:'', innerHTML:'', hidden:false, addEventListener(){}, setAttribute(){}});}\n"
            "const document = {documentElement:{lang:''}, title:'', getElementById:el, createElement(){return {textContent:'', get innerHTML(){return String(this.textContent);}}}, querySelectorAll(){return [];}};\n"
            "const location = {search:'', hash:''};\n"
            "const history = {pushState(){}, replaceState(){}};\n"
            "global.document = document; global.location = location; global.history = history; global.addEventListener = () => {};\n"
            "eval(require('fs').readFileSync(script, 'utf8'));\n"
            "const page = el('app').innerHTML;\n"
            "if (!page.includes('Show the v0.6.0 release in the guide\\'s download step.')) process.exit(2);\n"
            "if (!page.includes('<h2 class=\"lead\">')) process.exit(3);\n"
            "if (page.includes('Keep this project visible in OctoPulse.')) process.exit(4);\n"
            "if (!page.includes('scratch.txt')) process.exit(5);\n"
            "if (!page.includes('尚未寫入目標')) process.exit(6);\n",
            encoding="utf-8",
        )
        script_path = self.root / "report.js"
        script_path.write_text(script, encoding="utf-8")
        subprocess.run(["node", str(runner), str(script_path)], check=True)

    def test_session_record_stays_local_and_links_the_commit(self):
        project = self.make_git_project("Sessions")
        self.commit(project, "one.txt", "Record the conversation")
        previous = Path.cwd()
        try:
            os.chdir(project)
            self.assertEqual(cli.main(["session", "record", "--tool", "claude", "--session", "session-123"]), 0)
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", ".ai/octopulse-sessions.jsonl"], cwd=project).returncode, 0)
            status = subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True, check=True)
            self.assertNotIn("octopulse-sessions.jsonl", status.stdout)
            snapshot = reports.collect_project_snapshot(project, history=5)
            recorded = snapshot["history"][0]
            self.assertEqual(recorded["tool"], "claude")
            self.assertEqual(recorded["session"], "session-123")
            html = reports.project_html(snapshot, "zh-TW")
            self.assertIn("octopulse://resume?commit=", html)
            self.assertIn(recorded["commit_full"], html)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli.main(["resume", "--commit", recorded["commit_full"], "--dry-run"]), 0)
            self.assertEqual(json.loads(output.getvalue())["argv"], ["claude", "--resume", "session-123"])
            self.commit(project, "two.txt", "Manual edit")
            self.assertEqual(cli.main(["resume", "--commit", "HEAD"]), 1)
            self.commit(project, "three.txt", "Record tool only")
            self.assertEqual(cli.main(["session", "record", "--tool", "grok"]), 0)
            self.assertEqual(cli.main(["resume", "--commit", "HEAD"]), 1)
            self.assertEqual(cli.main(["resume", "--commit", "deadbeef"]), 1)
            markdown = reports.project_markdown(reports.collect_project_snapshot(project, history=5), "zh-TW")
            self.assertIn("Claude Code", markdown)
            self.assertIn("未記錄", markdown)
        finally:
            os.chdir(previous)

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
        self.assertIn("h.decisions.join('\\n')", html)
        self.assertNotIn("join('\n", html)
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
        payload = {"hookEventName": "stop", "hook_event_name": "Stop", "cwd": str(project), "prompt": "secret prompt must not leak"}
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
        legacy = self.make_git_project("LegacyGrok")
        core.write_json(legacy / ".octopulse", valid_marker("Legacy Grok"))
        core.add_root(legacy)
        self.assertEqual(self.run_hook(["hook", "grok-stop"], {"hookEventName": "Stop", "cwd": str(legacy), "prompt": "secret prompt must not leak"}), "")
        self.assertTrue(reports.snapshot_path(legacy).exists())
        self.assertNotIn("secret prompt", reports.snapshot_path(legacy).read_text(encoding="utf-8"))

    def test_update_yes_migrates_v2_and_publishes_reports_for_hooks(self):
        project = self.make_git_project("LegacyPulse")
        self.commit(project, "README.md", "legacy pulse")
        core.write_json(project / ".octopulse", legacy_marker("LegacyPulse"))
        original = (project / ".octopulse").read_text(encoding="utf-8")
        previous = Path.cwd()
        try:
            os.chdir(project)
            self.assertEqual(cli.main(["update"]), 2)
            self.assertEqual((project / ".octopulse").read_text(encoding="utf-8"), original)
            self.assertEqual(cli.main(["update", "--yes"]), 0)
            migrated = core.inspect_marker(project / ".octopulse")
            self.assertEqual(migrated["state"], "valid")
            self.assertEqual(migrated["payload"]["schema_version"], 3)
            self.assertEqual(migrated["payload"]["goal"], "Keep progress current.")
            self.assertIsNone(migrated["payload"]["handoff"])
            self.assertIn(str(project.resolve()), core.load_config()["roots"])
            self.assertTrue((reports.report_dir(project) / "index.html").is_file())
            portfolio = core.default_report_dir() / "index.html"
            self.assertIn("LegacyPulse", portfolio.read_text(encoding="utf-8"))
            self.assertEqual(cli.main(["update", "--yes", "--summary", "Only summary."]), 0)
            updated = core.inspect_marker(project / ".octopulse")["payload"]
            self.assertEqual(updated["summary"], "Only summary.")
            self.assertEqual(updated["goal"], "Keep progress current.")
            self.assertEqual(updated["next_action"], migrated["payload"]["next_action"])

            fresh = self.make_git_project("Fresh")
            os.chdir(fresh)
            self.assertEqual(cli.main(["update", "--yes", "--goal", "Ship.", "--next", "Open.", "--tool", "grok"]), 0)
            marker_bytes = (fresh / ".octopulse").read_bytes()
            self.assertIn("Fresh", (core.default_report_dir() / "index.html").read_text(encoding="utf-8"))
            self.assertEqual(self.run_hook(["hook", "grok-stop"], {"hookEventName": "stop", "hook_event_name": "Stop", "cwd": str(fresh), "prompt": "secret prompt must not leak"}), "")
            self.assertEqual((fresh / ".octopulse").read_bytes(), marker_bytes)
            self.assertNotIn("secret prompt", (reports.report_dir(fresh) / "snapshot.json").read_text(encoding="utf-8"))
        finally:
            os.chdir(previous)

    def test_claude_hooks_merge_without_replacing_other_settings(self):
        settings = self.root / "settings.json"
        settings.write_text(
            json.dumps({"model": "keep", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}]}}, indent=2) + "\n",
            encoding="utf-8",
        )
        result = hooks.install_claude_hooks(settings, "/opt/octopulse")
        self.assertTrue(result["changed"])
        config = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(config["model"], "keep")
        stop_commands = [handler["command"] for group in config["hooks"]["Stop"] for handler in group["hooks"]]
        self.assertEqual(stop_commands, ["echo other", "/opt/octopulse hook claude-stop"])
        session_commands = [handler["command"] for group in config["hooks"]["SessionStart"] for handler in group["hooks"]]
        self.assertEqual(session_commands, ["/opt/octopulse hook claude-session-start"])
        self.assertEqual(config["hooks"]["SessionStart"][0]["matcher"], "startup|resume|clear|compact|fork")
        self.assertFalse(hooks.install_claude_hooks(settings, "/opt/octopulse")["changed"])
        self.assertTrue(hooks.remove_claude_hooks(settings)["removed"])
        config = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(config["model"], "keep")
        self.assertEqual(config["hooks"]["Stop"], [{"hooks": [{"type": "command", "command": "echo other"}]}])
        self.assertNotIn("SessionStart", config["hooks"])

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
        self.assertTrue((home / ".codex" / "skills" / "octopulse" / "SKILL.md").is_file())
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

    def capture(self, arguments: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli.main(arguments)
        return code, output.getvalue()

    def test_status_and_update_cover_the_daily_path(self):
        project = self.make_git_project("Pulse")
        self.commit(project, "README.md", "initial pulse")
        previous = Path.cwd()
        try:
            os.chdir(project)
            code, text = self.capture(["status"])
            self.assertEqual(code, 0)
            self.assertIn("missing", text)
            self.assertIn("octopulse update --yes", text)
            self.assertEqual(cli.main(["update", "--goal", "Ship status.", "--next", "Run the tests."]), 2)
            self.assertFalse((project / ".octopulse").exists())
            self.assertEqual(cli.main(["update"]), 2)
            self.assertEqual(cli.main(["update", "--yes"]), 0)
            enrolled = core.inspect_marker(project / ".octopulse")
            self.assertEqual(enrolled["payload"]["goal"], core.DEFAULT_GOAL)
            self.assertEqual(enrolled["payload"]["next_action"], core.DEFAULT_NEXT)
            self.assertEqual(cli.main(["update", "--goal", "Ship status.", "--summary", "Ship status.", "--next", "Run the tests."]), 0)
            created = core.inspect_marker(project / ".octopulse")
            self.assertEqual(created["state"], "valid")
            self.assertEqual(created["payload"]["name"], "Pulse")
            self.assertEqual(created["payload"]["summary"], "Ship status.")
            self.assertEqual(created["payload"]["phase"], "implementation")
            self.assertEqual(created["payload"]["verification"]["status"], "not_run")
            self.assertIsNone(created["payload"]["handoff"])
            self.assertIn(str(project.resolve()), core.load_config()["roots"])

            code, text = self.capture([])
            self.assertEqual(code, 0)
            self.assertIn("Ship status.", text)
            self.assertIn("Run the tests.", text)
            self.assertIn("initial pulse", text)
            code, english = self.capture(["status", "--lang", "en"])
            self.assertIn("Goal: Ship status.", english)
            code, raw = self.capture(["status", "--json"])
            view = json.loads(raw)
            self.assertEqual(view["state"], "valid")
            self.assertEqual(view["status"]["goal"], "Ship status.")
            self.assertEqual(view["git"]["subject"], "initial pulse")
            code, raw = self.capture(["context"])
            self.assertEqual(set(json.loads(raw)), {"project_root", "marker", "state", "registered", "errors"})

            self.assertEqual(cli.main(["handoff", "create", "--tool", "grok", "--decision", "Keep the daily path short."]), 0)
            self.assertEqual(cli.main(["update", "--verify-status", "passed", "--verify-command", "python3 -m unittest"]), 0)
            verified = core.inspect_marker(project / ".octopulse")["payload"]
            self.assertEqual(cli.main(["update", "--summary", "Only the summary changes.", "--attention", "One", "--attention", "Two"]), 0)
            updated = core.inspect_marker(project / ".octopulse")["payload"]
            self.assertEqual(updated["summary"], "Only the summary changes.")
            self.assertEqual(updated["goal"], verified["goal"])
            self.assertEqual(updated["next_action"], verified["next_action"])
            self.assertEqual(updated["handoff"], verified["handoff"])
            self.assertEqual(updated["attention"], ["One", "Two"])
            self.assertEqual(updated["verification"], verified["verification"])

            empty = self.make_git_project("Empty")
            os.chdir(empty)
            (empty / ".octopulse").write_text("", encoding="utf-8")
            self.assertEqual(cli.main(["update", "--goal", "Fill.", "--next", "Done."]), 2)
            self.assertEqual((empty / ".octopulse").read_text(encoding="utf-8"), "")
            self.assertEqual(cli.main(["update", "--yes", "--goal", "Fill.", "--next", "Done."]), 0)
            self.assertEqual(core.inspect_marker(empty / ".octopulse")["payload"]["goal"], "Fill.")
            os.chdir(project)

            self.assertEqual(cli.main(["update", "--tool", "grok", "--result", "unchanged"]), 0)
            events = [json.loads(line) for line in reports.activity_path(project).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(events, [{"timestamp": events[0]["timestamp"], "tool": "grok", "event": "finish", "result": "unchanged"}])
            self.assertEqual(core.inspect_marker(project / ".octopulse")["payload"]["summary"], "Only the summary changes.")
            self.assertTrue((reports.report_dir(project) / "latest.md").is_file())

            core.write_json(project / ".octopulse", legacy_marker("Pulse"))
            self.assertEqual(cli.main(["update", "--summary", "blocked"]), 2)
            self.assertEqual(core.inspect_marker(project / ".octopulse")["state"], "migration_required")
            (project / ".octopulse").write_text("{", encoding="utf-8")
            self.assertEqual(cli.main(["update", "--summary", "blocked"]), 1)
            code, text = self.capture(["status"])
            self.assertIn("invalid", text)
            self.assertIn("octopulse validate .octopulse", text)
        finally:
            os.chdir(previous)

    def test_archive_overwrites_regular_marker_and_rejects_symlink(self):
        project = self.make_git_project()
        previous = Path.cwd()
        try:
            os.chdir(project)
            self.assertEqual(cli.main(["update", "--yes", "--goal", "Active.", "--next", "Continue."]), 0)
            self.assertEqual(cli.main(["archive", "--yes", "--reason", "Parked."]), 0)
            payload = core.inspect_marker(project / ".octopulse")["payload"]
            self.assertEqual(payload["phase"], "paused")
            self.assertEqual(payload["health"], "stale")
            self.assertEqual(payload["summary"], "Parked.")
            marker = project / ".octopulse"
            marker.unlink()
            marker.symlink_to("README")
            self.assertEqual(cli.main(["archive", "--yes", "--force", "--reason", "nope"]), 1)
            self.assertTrue(marker.is_symlink())
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
