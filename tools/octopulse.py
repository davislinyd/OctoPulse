#!/usr/bin/env python3
"""OctoPulse v2 command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from octopulse import core, hooks, reports


GUIDANCE_BLOCK = """<!-- octopulse:start -->
## OctoPulse

Use the global `OctoPulse` skill at the start and end of non-trivial work. It may read only `.otcopulse` plus lightweight Git facts; ask before creating or repairing the marker.
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
    if marker.exists() and not args.force:
        print(f"error: {marker} already exists (use --force only after review)", file=sys.stderr)
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


def hook_payload() -> dict | None:
    return hooks.read_payload(sys.stdin)


def command_hook_session_start(args: argparse.Namespace) -> int:
    payload = hook_payload()
    if not payload or payload.get("hook_event_name") != "SessionStart":
        return 0
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or reports.eligible_hook_project(Path(cwd)) is None:
        return 0
    print(hooks.session_start_output())
    return 0


def command_hook_stop(args: argparse.Namespace) -> int:
    payload = hook_payload()
    if not payload or payload.get("hook_event_name") != "Stop":
        return 0
    cwd = payload.get("cwd")
    if not isinstance(cwd, str):
        return 0
    return refresh_hook_reports(cwd)


def command_hook_grok_stop(args: argparse.Namespace) -> int:
    payload = hook_payload()
    if not payload or payload.get("hookEventName") != "Stop":
        return 0
    cwd = payload.get("cwd")
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


def command_hook_install_grok(args: argparse.Namespace) -> int:
    result = hooks.install_grok_hooks(Path(args.hooks_file).expanduser(), args.command)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_hook_remove_grok(args: argparse.Namespace) -> int:
    result = hooks.remove_grok_hooks(Path(args.hooks_file).expanduser())
    print(json.dumps(result, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OctoPulse v2 marker-based status CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {core.RELEASE_VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="Create an empty marker after confirmation")
    init.add_argument("--directory")
    init.add_argument("--yes", action="store_true")
    init.add_argument("--force", action="store_true")
    init.add_argument("--agent", choices=["codex", "claude", "antigravity", "grok", "all"])
    init.set_defaults(handler=command_init)
    context = subparsers.add_parser("context", help="Inspect the current project without writing")
    context.add_argument("--directory")
    context.set_defaults(handler=command_context)
    validate = subparsers.add_parser("validate", help="Validate one .otcopulse marker")
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
    report.add_argument("--history", type=int, default=10)
    report.add_argument("--legacy-status", choices=["auto", "never"], default="auto")
    report.add_argument("--lang", choices=["zh-TW", "en"], default="zh-TW")
    report.set_defaults(handler=command_report)
    project = subparsers.add_parser("project", help="Create one project report")
    project_subparsers = project.add_subparsers(dest="project_command", required=True)
    project_report = project_subparsers.add_parser("report")
    project_report.add_argument("--project")
    project_report.add_argument("--history", type=int, default=10)
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
    portfolio_report.add_argument("--history", type=int, default=10)
    portfolio_report.add_argument("--legacy-status", choices=["auto", "never"], default="auto")
    portfolio_report.add_argument("--lang", choices=["zh-TW", "en"], default="zh-TW")
    portfolio_report.set_defaults(handler=command_portfolio_report)
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
    grok_stop = hook_subparsers.add_parser("grok-stop")
    grok_stop.set_defaults(handler=command_hook_grok_stop)
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
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
