#!/usr/bin/env python3
"""OctoPulse v3 command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from octopulse import core, hooks, reports


GUIDANCE_BLOCK = """<!-- octopulse:start -->
## OctoPulse

Use the global `OctoPulse` skill. Without an explicit request to change progress, only read `octopulse status` and the portfolio report. When the user asks to put this project into OctoPulse, enroll it with `octopulse update --yes` and do not ask for a goal or next action. Before switching models, run `octopulse handoff show` or `octopulse handoff create`, then commit and push `.octopulse` with the work.
<!-- octopulse:end -->
"""


def current_directory(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else Path.cwd()


def require_yes(args: argparse.Namespace) -> bool:
    if args.yes:
        return True
    print("confirmation required: rerun with --yes after user approval", file=sys.stderr)
    return False


def inject_guidance(root: Path, agent: str) -> list[Path]:
    names = []
    for item in (["codex", "claude", "antigravity", "grok"] if agent == "all" else [agent]):
        names.append("CLAUDE.md" if item == "claude" else "AGENTS.md")
    changed: list[Path] = []
    for name in sorted(set(names)):
        path = root / name
        original = path.read_text(encoding="utf-8") if path.exists() else ""
        if "<!-- octopulse:start -->" in original and "<!-- octopulse:end -->" in original:
            before, remainder = original.split("<!-- octopulse:start -->", 1)
            _, after = remainder.split("<!-- octopulse:end -->", 1)
            updated = before.rstrip() + "\n\n" + GUIDANCE_BLOCK + after.lstrip()
        else:
            updated = original.rstrip() + ("\n\n" if original.strip() else "") + GUIDANCE_BLOCK
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed


def command_init(args: argparse.Namespace) -> int:
    if not require_yes(args):
        return 2
    root = core.git_root(current_directory(args.directory))
    if root is None:
        print("error: current directory is not inside a Git work tree", file=sys.stderr)
        return 1
    marker = root / core.MARKER_NAME
    if marker.exists() and not args.force:
        print(f"error: {marker} already exists (use --force only after review)", file=sys.stderr)
        return 1
    if marker.exists() and args.force:
        marker.unlink()
    marker.touch()
    added = core.add_root(root)
    reports.ensure_local_exclude(root)
    changed = inject_guidance(root, args.agent) if args.agent else []
    print(json.dumps({"marker": str(marker), "root_added": added, "guidance_updated": [str(path) for path in changed]}, ensure_ascii=False))
    return 0


def command_context(args: argparse.Namespace) -> int:
    print(json.dumps(core.context_for(current_directory(args.directory)), ensure_ascii=False))
    return 0


def command_migrate_marker(args: argparse.Namespace) -> int:
    if not require_yes(args):
        return 2
    root = core.git_root(current_directory(args.directory))
    if root is None:
        print("error: current directory is not inside a Git work tree", file=sys.stderr)
        return 1
    source = root / core.LEGACY_MARKER_NAME
    target = root / core.MARKER_NAME
    if source.exists() and target.exists():
        print(f"error: both {source} and {target} exist; resolve the conflict before migrating", file=sys.stderr)
        return 1
    if target.exists():
        print(json.dumps({"project_root": str(root), "marker": str(target), "state": "already_migrated"}, ensure_ascii=False))
        return 0
    if not source.exists():
        print(json.dumps({"project_root": str(root), "marker": str(target), "state": "missing"}, ensure_ascii=False))
        return 0
    if source.is_symlink() or not source.is_file():
        print(f"error: {source} must be a regular file", file=sys.stderr)
        return 1
    source.replace(target)
    print(json.dumps({"project_root": str(root), "source": str(source), "marker": str(target), "state": "migrated"}, ensure_ascii=False))
    return 0


def command_migrate_schema(args: argparse.Namespace) -> int:
    if not require_yes(args):
        return 2
    root = core.git_root(current_directory(args.directory))
    if root is None:
        print("error: current directory is not inside a Git work tree", file=sys.stderr)
        return 1
    marker = root / core.MARKER_NAME
    inspection = core.inspect_marker(marker)
    if inspection["state"] == "valid":
        print(json.dumps({"project_root": str(root), "marker": str(marker), "state": "already_current"}, ensure_ascii=False))
        return 0
    if inspection["state"] != "migration_required":
        print(f"error: schema migration requires a valid v{core.LEGACY_SCHEMA_VERSION} marker (current state: {inspection['state']})", file=sys.stderr)
        return 1
    payload = dict(inspection["payload"])
    payload["schema_version"] = core.VERSION
    payload["handoff"] = None
    errors = core.validate_marker_payload(payload, str(marker))
    if errors:
        print("\n".join(f"error: {error}" for error in errors), file=sys.stderr)
        return 1
    core.write_json(marker, payload)
    print(json.dumps({"project_root": str(root), "marker": str(marker), "state": "migrated", "schema_version": core.VERSION}, ensure_ascii=False))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    inspected = core.inspect_marker(Path(args.marker).expanduser())
    print(json.dumps(inspected, ensure_ascii=False))
    return 0 if inspected["state"] == "valid" else 1


def command_root(args: argparse.Namespace) -> int:
    if args.root_command == "list":
        print("\n".join(core.load_config()["roots"]))
        return 0
    path = Path(args.path).expanduser().resolve()
    if args.root_command == "add":
        if not path.is_dir():
            print(f"error: {path} is not a directory", file=sys.stderr)
            return 1
        print("added" if core.add_root(path) else "already registered")
    else:
        print("removed" if core.remove_root(path) else "not registered")
    return 0


def command_report(args: argparse.Namespace) -> int:
    return command_portfolio_report(args)


def command_project_report(args: argparse.Namespace) -> int:
    directory = current_directory(args.project)
    root = core.git_root(directory)
    if root is None:
        print("error: project must be inside a Git work tree", file=sys.stderr)
        return 1
    snapshot, cached = reports.refresh_project_report(root, args.history, args.legacy_status, args.lang, force=args.refresh == "all")
    print(json.dumps({"project": str(root), "output": str(reports.report_dir(root)), "cached": cached, "signals": snapshot["signals"]}, ensure_ascii=False))
    return 0


def command_portfolio_report(args: argparse.Namespace) -> int:
    portfolio, refreshed = reports.collect_portfolio(args.refresh, args.history, args.legacy_status, args.lang)
    output = Path(args.output).expanduser() if args.output else core.default_report_dir()
    written = reports.write_portfolio_report(portfolio, output, args.lang, getattr(args, "format", "both"))
    result = {"projects": len(portfolio["projects"]), "output": str(output), "cached": not refreshed and not written, "refreshed_projects": refreshed, "written": [str(path) for path in written]}
    if args.explain:
        result["refresh"] = args.refresh
        result["data_source"] = "project snapshots"
        result["missing_project_reports"] = [item["project"]["path"] for item in portfolio["projects"] if item.get("state") == "missing_project_report"]
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_archive(args: argparse.Namespace) -> int:
    if not require_yes(args):
        return 2
    root = core.git_root(current_directory(args.directory))
    if root is None:
        print("error: current directory is not inside a Git work tree", file=sys.stderr)
        return 1
    marker = root / core.MARKER_NAME
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        print(f"error: {marker} must be a regular file", file=sys.stderr)
        return 1
    payload = core.archive_marker(root, args.reason)
    errors = core.validate_marker_payload(payload, str(marker))
    if errors:
        print("\n".join(f"error: {error}" for error in errors), file=sys.stderr)
        return 1
    core.write_json(marker, payload)
    core.add_root(root)
    reports.ensure_local_exclude(root)
    print(json.dumps({"marker": str(marker), "mode": "archived", "health": "stale"}, ensure_ascii=False))
    return 0


def command_activity(args: argparse.Namespace) -> int:
    root = core.git_root(current_directory(args.project))
    if root is None:
        print("error: project must be inside a Git work tree", file=sys.stderr)
        return 1
    entry = reports.record_activity(root, args.tool, args.activity_command, getattr(args, "result", None))
    print(json.dumps({"project": str(root), "activity": entry}, ensure_ascii=False))
    return 0


def command_session_record(args: argparse.Namespace) -> int:
    root = core.git_root(current_directory(args.project))
    if root is None:
        print("error: project must be inside a Git work tree", file=sys.stderr)
        return 1
    entry = reports.record_session(root, args.commit, args.tool, args.session)
    print(json.dumps(entry, ensure_ascii=False))
    return 0


def command_session_install_handler(args: argparse.Namespace) -> int:
    binary = str(Path(sys.argv[0]).resolve()) if Path(sys.argv[0]).exists() else "octopulse"
    app = reports.install_resume_handler(Path.home() / "Applications", binary)
    lsregister = Path("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister")
    if lsregister.is_file():
        os.spawnv(os.P_WAIT, str(lsregister), [str(lsregister), "-f", str(app)])
    print(json.dumps({"app": str(app)}, ensure_ascii=False))
    return 0


def command_resume(args: argparse.Namespace) -> int:
    directory = current_directory(args.project) if args.project else Path.cwd()
    root, full = reports.find_session_root(args.commit, directory)
    argv = reports.resume_argv(root, full)
    if args.dry_run:
        print(json.dumps({"argv": argv, "commit": full}, ensure_ascii=False))
        return 0
    os.execvp(argv[0], argv)


def command_handoff_create(args: argparse.Namespace) -> int:
    root = core.git_root(current_directory(args.project))
    if root is None:
        print("error: project must be inside a Git work tree", file=sys.stderr)
        return 1
    payload = core.create_handoff(root, args.tool, args.read_first, args.decision)
    print(json.dumps({"project": str(root), "handoff": payload["handoff"]}, ensure_ascii=False))
    return 0


def command_handoff_show(args: argparse.Namespace) -> int:
    root = core.git_root(current_directory(args.project))
    if root is None:
        print("error: project must be inside a Git work tree", file=sys.stderr)
        return 1
    print(json.dumps(core.handoff_resume_packet(root), ensure_ascii=False))
    return 0


def command_status(args: argparse.Namespace) -> int:
    view = core.status_view(current_directory(args.directory))
    if args.json:
        print(json.dumps(view, ensure_ascii=False))
    else:
        print(core.format_status(view, args.lang), end="")
    return 0


def _update_requested(args: argparse.Namespace) -> bool:
    return any(
        value is not None
        for value in (args.name, args.phase, args.health, args.goal, args.summary, args.next, args.verify_status, args.verify_command, args.attention)
    )


def _refresh_reports(root: Path, language: str) -> None:
    reports.refresh_project_report(root, language=language)
    portfolio, _refreshed = reports.collect_portfolio(refresh="auto", language=language)
    reports.write_portfolio_report(portfolio, core.default_report_dir(), language)


def command_update(args: argparse.Namespace) -> int:
    root = core.git_root(current_directory(args.directory))
    if root is None:
        print("error: current directory is not inside a Git work tree", file=sys.stderr)
        return 1
    marker = root / core.MARKER_NAME
    inspection = core.inspect_marker(marker)
    creating = inspection["state"] in {"missing", "uninitialized"}
    migrating = inspection["state"] == "migration_required"
    if not _update_requested(args) and not args.tool and not (args.yes and (creating or migrating)):
        print("error: update requires a field or --tool", file=sys.stderr)
        return 2
    if creating:
        if not require_yes(args):
            return 2
        goal = args.goal if args.goal and args.goal.strip() else core.DEFAULT_GOAL
        next_action = args.next if args.next and args.next.strip() else core.DEFAULT_NEXT
        payload = core.new_marker(root, goal, next_action, args.summary, args.name, args.phase or "implementation", args.health or "active")
    elif migrating:
        if not require_yes(args):
            return 2
        payload = dict(inspection["payload"])
        payload["schema_version"] = core.VERSION
        payload["handoff"] = None
        payload["verification"] = dict(payload["verification"])
    elif inspection["state"] != "valid":
        print(f"error: refusing to update an invalid marker (current state: {inspection['state']})", file=sys.stderr)
        return 1
    else:
        payload = dict(inspection["payload"])
        payload["verification"] = dict(payload["verification"])
    if not creating:
        if args.name is not None:
            payload["name"] = args.name
        if args.phase is not None:
            payload["phase"] = args.phase
        if args.health is not None:
            payload["health"] = args.health
        if args.goal is not None:
            payload["goal"] = args.goal
        if args.summary is not None:
            payload["summary"] = args.summary
        if args.next is not None:
            payload["next_action"] = args.next
    if args.attention is not None:
        payload["attention"] = args.attention
    if args.verify_status is not None or args.verify_command is not None:
        if args.verify_status is not None:
            payload["verification"]["status"] = args.verify_status
        if args.verify_command is not None:
            payload["verification"]["last_command"] = args.verify_command
        payload["verification"]["last_verified_at"] = core.now_iso()
    wrote = creating or migrating or _update_requested(args)
    if wrote:
        payload["last_updated"] = core.now_iso()
        errors = core.validate_marker_payload(payload, str(marker))
        if errors:
            print("\n".join(f"error: {error}" for error in errors), file=sys.stderr)
            return 1
        core.write_json(marker, payload)
        if creating or migrating:
            core.add_root(root)
            reports.ensure_local_exclude(root)
    activity = None
    if args.tool:
        activity = reports.record_activity(root, args.tool, "finish", args.result)
    if wrote or args.tool:
        _refresh_reports(root, args.lang)
    result = {"project": str(root), "marker": str(marker), "created": creating, "migrated": migrating, "status": payload}
    if activity is not None:
        result["activity"] = activity
    print(json.dumps(result, ensure_ascii=False))
    return 0


def hook_payload() -> dict | None:
    return hooks.read_payload(sys.stdin)


def command_hook_session_start(args: argparse.Namespace) -> int:
    payload = hook_payload()
    if hooks.canonical_event_name(payload) != "SessionStart":
        return 0
    cwd = payload.get("cwd") if payload else None
    if not isinstance(cwd, str) or reports.eligible_hook_project(Path(cwd)) is None:
        return 0
    print(hooks.session_start_output())
    return 0


def command_hook_stop(args: argparse.Namespace) -> int:
    payload = hook_payload()
    if hooks.canonical_event_name(payload) != "Stop":
        return 0
    cwd = payload.get("cwd") if payload else None
    if not isinstance(cwd, str):
        return 0
    return refresh_hook_reports(cwd)


def refresh_hook_reports(cwd: str) -> int:
    root = reports.eligible_hook_project(Path(cwd))
    if root is None:
        return 0
    try:
        with reports.project_hook_lock(root) as locked:
            if not locked:
                return 0
            _, cached = reports.refresh_project_report(root, language="zh-TW")
        if cached:
            return 0
        with reports.portfolio_hook_lock() as locked:
            if not locked:
                return 0
            portfolio, _ = reports.collect_portfolio(refresh="never", language="zh-TW")
            reports.write_portfolio_report(portfolio, core.default_report_dir(), "zh-TW")
    except (OSError, ValueError):
        return 0
    return 0


def command_hook_install_codex(args: argparse.Namespace) -> int:
    result = hooks.install_codex_hooks(Path(args.hooks_file).expanduser(), args.command)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_hook_remove_codex(args: argparse.Namespace) -> int:
    result = hooks.remove_codex_hooks(Path(args.hooks_file).expanduser())
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_hook_install_claude(args: argparse.Namespace) -> int:
    result = hooks.install_claude_hooks(Path(args.hooks_file).expanduser(), args.command)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_hook_remove_claude(args: argparse.Namespace) -> int:
    result = hooks.remove_claude_hooks(Path(args.hooks_file).expanduser())
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_hook_install_grok(args: argparse.Namespace) -> int:
    result = hooks.install_grok_hooks(Path(args.hooks_file).expanduser(), args.command)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_hook_remove_grok(args: argparse.Namespace) -> int:
    result = hooks.remove_grok_hooks(Path(args.hooks_file).expanduser())
    print(json.dumps(result, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OctoPulse v3 marker-based status CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {core.RELEASE_VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="Print the current project pulse")
    status.add_argument("--directory")
    status.add_argument("--json", action="store_true")
    status.add_argument("--lang", choices=["zh-TW", "en"], default="zh-TW")
    status.set_defaults(handler=command_status)
    update = subparsers.add_parser("update", help="Create or patch the current project pulse")
    update.add_argument("--directory")
    update.add_argument("--yes", action="store_true")
    update.add_argument("--name")
    update.add_argument("--phase", choices=sorted(core.PHASES))
    update.add_argument("--health", choices=sorted(core.HEALTH_VALUES))
    update.add_argument("--goal")
    update.add_argument("--summary")
    update.add_argument("--next")
    update.add_argument("--attention", action="append")
    update.add_argument("--verify-status", choices=sorted(core.VERIFICATION_VALUES))
    update.add_argument("--verify-command")
    update.add_argument("--tool", choices=sorted(reports.TOOLS))
    update.add_argument("--result", choices=sorted(reports.RESULTS), default="updated")
    update.add_argument("--lang", choices=["zh-TW", "en"], default="zh-TW")
    update.set_defaults(handler=command_update)
    init = subparsers.add_parser("init", help="Create an empty marker after confirmation")
    init.add_argument("--directory")
    init.add_argument("--yes", action="store_true")
    init.add_argument("--force", action="store_true")
    init.add_argument("--agent", choices=["codex", "claude", "antigravity", "grok", "all"])
    init.set_defaults(handler=command_init)
    context = subparsers.add_parser("context", help="Inspect the current project without writing")
    context.add_argument("--directory")
    context.set_defaults(handler=command_context)
    migrate_marker = subparsers.add_parser("migrate-marker", help="Rename one legacy .otcopulse marker after confirmation")
    migrate_marker.add_argument("--directory")
    migrate_marker.add_argument("--yes", action="store_true")
    migrate_marker.set_defaults(handler=command_migrate_marker)
    migrate_schema = subparsers.add_parser("migrate-schema", help="Upgrade one valid v2 marker to the current schema after confirmation")
    migrate_schema.add_argument("--directory")
    migrate_schema.add_argument("--yes", action="store_true")
    migrate_schema.set_defaults(handler=command_migrate_schema)
    validate = subparsers.add_parser("validate", help="Validate one .octopulse marker")
    validate.add_argument("marker", type=Path)
    validate.set_defaults(handler=command_validate)
    root = subparsers.add_parser("root", help="Manage trusted discovery roots")
    root_subparsers = root.add_subparsers(dest="root_command", required=True)
    root_list = root_subparsers.add_parser("list")
    root_list.set_defaults(handler=command_root)
    for name in ["add", "remove"]:
        item = root_subparsers.add_parser(name)
        item.add_argument("path")
        item.set_defaults(handler=command_root)
    report = subparsers.add_parser("report", help="Compatibility alias for `portfolio report`")
    report.add_argument("--format", choices=["markdown", "html", "both"], default="both")
    report.add_argument("--output")
    report.add_argument("--explain", action="store_true")
    report.add_argument("--refresh", choices=["auto", "never", "all"], default="auto")
    report.add_argument("--history", type=int, default=20)
    report.add_argument("--legacy-status", choices=["auto", "never"], default="auto")
    report.add_argument("--lang", choices=["zh-TW", "en"], default="zh-TW")
    report.set_defaults(handler=command_report)
    project = subparsers.add_parser("project", help="Create one project report")
    project_subparsers = project.add_subparsers(dest="project_command", required=True)
    project_report = project_subparsers.add_parser("report")
    project_report.add_argument("--project")
    project_report.add_argument("--history", type=int, default=20)
    project_report.add_argument("--legacy-status", choices=["auto", "never"], default="auto")
    project_report.add_argument("--lang", choices=["zh-TW", "en"], default="zh-TW")
    project_report.add_argument("--refresh", choices=["auto", "all"], default="auto")
    project_report.set_defaults(handler=command_project_report)
    portfolio = subparsers.add_parser("portfolio", help="Create a report for all registered projects")
    portfolio_subparsers = portfolio.add_subparsers(dest="portfolio_command", required=True)
    portfolio_report = portfolio_subparsers.add_parser("report")
    portfolio_report.add_argument("--output")
    portfolio_report.add_argument("--explain", action="store_true")
    portfolio_report.add_argument("--refresh", choices=["auto", "never", "all"], default="auto")
    portfolio_report.add_argument("--history", type=int, default=20)
    portfolio_report.add_argument("--legacy-status", choices=["auto", "never"], default="auto")
    portfolio_report.add_argument("--lang", choices=["zh-TW", "en"], default="zh-TW")
    portfolio_report.set_defaults(handler=command_portfolio_report)
    session = subparsers.add_parser("session", help="Record which local AI conversation made a commit")
    session_subparsers = session.add_subparsers(dest="session_command", required=True)
    session_record = session_subparsers.add_parser("record")
    session_record.add_argument("--project")
    session_record.add_argument("--commit", default="HEAD")
    session_record.add_argument("--tool", choices=sorted(reports.SESSION_TOOLS), required=True)
    session_record.add_argument("--session")
    session_record.set_defaults(handler=command_session_record)
    session_handler = session_subparsers.add_parser("install-handler")
    session_handler.set_defaults(handler=command_session_install_handler)
    resume = subparsers.add_parser("resume", help="Open the local AI conversation recorded for a commit")
    resume.add_argument("--commit", required=True)
    resume.add_argument("--project")
    resume.add_argument("--dry-run", action="store_true")
    resume.set_defaults(handler=command_resume)
    activity = subparsers.add_parser("activity", help="Record a non-trivial AI tool session")
    activity_subparsers = activity.add_subparsers(dest="activity_command", required=True)
    activity_start = activity_subparsers.add_parser("start")
    activity_start.add_argument("--project")
    activity_start.add_argument("--tool", choices=sorted(reports.TOOLS), required=True)
    activity_start.set_defaults(handler=command_activity)
    activity_finish = activity_subparsers.add_parser("finish")
    activity_finish.add_argument("--project")
    activity_finish.add_argument("--tool", choices=sorted(reports.TOOLS), required=True)
    activity_finish.add_argument("--result", choices=sorted(reports.RESULTS), default="updated")
    activity_finish.set_defaults(handler=command_activity)
    handoff = subparsers.add_parser("handoff", help="Create or read a compact cross-model handoff")
    handoff_subparsers = handoff.add_subparsers(dest="handoff_command", required=True)
    handoff_create = handoff_subparsers.add_parser("create", help="Write the latest structured handoff")
    handoff_create.add_argument("--project")
    handoff_create.add_argument("--tool", choices=sorted(core.HANDOFF_TOOLS), required=True)
    handoff_create.add_argument("--read-first", action="append", default=[])
    handoff_create.add_argument("--decision", action="append", default=[])
    handoff_create.set_defaults(handler=command_handoff_create)
    handoff_show = handoff_subparsers.add_parser("show", help="Print the compact resume packet")
    handoff_show.add_argument("--project")
    handoff_show.set_defaults(handler=command_handoff_show)
    hook = subparsers.add_parser("hook", help="Run or manage narrowly scoped agent hooks")
    hook_subparsers = hook.add_subparsers(dest="hook_command", required=True)
    hook_session_start = hook_subparsers.add_parser("codex-session-start")
    hook_session_start.set_defaults(handler=command_hook_session_start)
    hook_stop = hook_subparsers.add_parser("codex-stop")
    hook_stop.set_defaults(handler=command_hook_stop)
    hook_install = hook_subparsers.add_parser("codex-install")
    hook_install.add_argument("--hooks-file", required=True)
    hook_install.add_argument("--command", required=True)
    hook_install.set_defaults(handler=command_hook_install_codex)
    hook_remove = hook_subparsers.add_parser("codex-remove")
    hook_remove.add_argument("--hooks-file", required=True)
    hook_remove.set_defaults(handler=command_hook_remove_codex)
    claude_session_start = hook_subparsers.add_parser("claude-session-start")
    claude_session_start.set_defaults(handler=command_hook_session_start)
    claude_stop = hook_subparsers.add_parser("claude-stop")
    claude_stop.set_defaults(handler=command_hook_stop)
    claude_install = hook_subparsers.add_parser("claude-install")
    claude_install.add_argument("--hooks-file", required=True)
    claude_install.add_argument("--command", required=True)
    claude_install.set_defaults(handler=command_hook_install_claude)
    claude_remove = hook_subparsers.add_parser("claude-remove")
    claude_remove.add_argument("--hooks-file", required=True)
    claude_remove.set_defaults(handler=command_hook_remove_claude)
    grok_stop = hook_subparsers.add_parser("grok-stop")
    grok_stop.set_defaults(handler=command_hook_stop)
    grok_install = hook_subparsers.add_parser("grok-install")
    grok_install.add_argument("--hooks-file", required=True)
    grok_install.add_argument("--command", required=True)
    grok_install.set_defaults(handler=command_hook_install_grok)
    grok_remove = hook_subparsers.add_parser("grok-remove")
    grok_remove.add_argument("--hooks-file", required=True)
    grok_remove.set_defaults(handler=command_hook_remove_grok)
    archive = subparsers.add_parser("archive", help="Create a source-free stale pulse for a retired project")
    archive.add_argument("--directory")
    archive.add_argument("--yes", action="store_true")
    archive.add_argument("--force", action="store_true")
    archive.add_argument("--reason", required=True)
    archive.set_defaults(handler=command_archive)
    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["status"]
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
