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

from octopulse import core


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
    for item in (["codex", "claude", "antigravity"] if agent == "all" else [agent]):
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
    entries, reads, missing_roots = core.scan_projects()
    result_fingerprint = core.fingerprint(entries)
    output = Path(args.output).expanduser() if args.output else core.default_report_dir()
    cache = core.load_cache()
    expected = [output / "projects.json"]
    if args.format in {"markdown", "both"}:
        expected.append(output / "latest.md")
    if args.format in {"html", "both"}:
        expected.append(output / "index.html")
    unchanged = cache.get("fingerprint") == result_fingerprint and all(path.exists() for path in expected)
    written = [] if unchanged else core.write_report(entries, output, args.format)
    if not unchanged:
        core.write_json(core.cache_path(), {"schema_version": core.VERSION, "fingerprint": result_fingerprint})
    result = {"projects": len(entries), "output": str(output), "cached": unchanged, "written": [str(path) for path in written]}
    if args.explain:
        result["marker_reads"] = reads
        result["missing_roots"] = missing_roots
        result["reason"] = "fingerprint unchanged" if unchanged else "marker or Git facts changed, or requested output is missing"
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
    print(json.dumps({"marker": str(marker), "mode": "archived", "health": "stale"}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OctoPulse v2 marker-based status CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {core.RELEASE_VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="Create an empty marker after confirmation")
    init.add_argument("--directory")
    init.add_argument("--yes", action="store_true")
    init.add_argument("--force", action="store_true")
    init.add_argument("--agent", choices=["codex", "claude", "antigravity", "all"])
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
    report = subparsers.add_parser("report", help="Render marker-only reports")
    report.add_argument("--format", choices=["markdown", "html", "both"], default="both")
    report.add_argument("--output")
    report.add_argument("--explain", action="store_true")
    report.set_defaults(handler=command_report)
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
