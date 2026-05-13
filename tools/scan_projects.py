#!/usr/bin/env python3
"""Scan OctoPulse project status pulses and generate aggregate outputs."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from validate_status import parse_iso_datetime, validate_status_file


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECTS_FILE = REPO_ROOT / "projects.yaml"
STATE_FILE = REPO_ROOT / "state" / "projects.json"
REPORT_FILE = REPO_ROOT / "reports" / "latest.md"
DASHBOARD_FILE = REPO_ROOT / "dashboard" / "index.html"

GROUP_ORDER = [
    ("blocked", "Blocked"),
    ("needs_attention", "Needs Attention"),
    ("active", "Active"),
    ("stable", "Stable"),
    ("stale", "Stale"),
    ("missing_project", "Missing Project"),
    ("missing_status", "Missing Status"),
    ("invalid_status", "Invalid Status"),
]


@dataclass
class ProjectConfig:
    name: str
    path: Path
    status_file: Path
    detail_file: Path


def now_local() -> datetime:
    return datetime.now().astimezone()


def iso_now() -> str:
    return now_local().isoformat(timespec="seconds")


def parse_projects_yaml(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ValueError(f"{path}: file does not exist")

    projects: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    saw_projects_key = False

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not saw_projects_key:
            if stripped != "projects:":
                raise ValueError(f"{path}:{line_number}: expected top-level `projects:` key")
            saw_projects_key = True
            continue

        if line.startswith("  - "):
            if current is not None:
                projects.append(current)
            current = {}
            remainder = line[4:].strip()
            if remainder:
                key, value = parse_key_value(path, line_number, remainder)
                current[key] = value
            continue

        if line.startswith("    "):
            if current is None:
                raise ValueError(f"{path}:{line_number}: project field found before list item")
            key, value = parse_key_value(path, line_number, stripped)
            current[key] = value
            continue

        raise ValueError(f"{path}:{line_number}: unsupported YAML shape")

    if current is not None:
        projects.append(current)

    if not saw_projects_key:
        raise ValueError(f"{path}: missing top-level `projects:` key")
    return projects


def parse_key_value(path: Path, line_number: int, text: str) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"{path}:{line_number}: expected `key: value`")
    key, value = text.split(":", 1)
    key = key.strip()
    value = parse_scalar(value.strip())
    if not key:
        raise ValueError(f"{path}:{line_number}: key cannot be empty")
    return key, value


def parse_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def resolve_path(base: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def load_project_configs(projects_file: Path) -> list[ProjectConfig]:
    raw_projects = parse_projects_yaml(projects_file)
    configs: list[ProjectConfig] = []
    errors: list[str] = []

    for index, item in enumerate(raw_projects, start=1):
        item_errors: list[str] = []
        for field in ["name", "path", "status_file"]:
            if field not in item:
                item_errors.append(f"{projects_file}: project #{index} is missing `{field}`")
        if item_errors:
            errors.extend(item_errors)
            continue

        project_path = resolve_path(REPO_ROOT, item["path"])
        status_file = resolve_child_path(project_path, item["status_file"])
        detail_file = resolve_child_path(project_path, item.get("detail_file", "PROJECT_STATUS.md"))
        configs.append(
            ProjectConfig(
                name=item["name"],
                path=project_path,
                status_file=status_file,
                detail_file=detail_file,
            )
        )

    if errors:
        raise ValueError("\n".join(errors))
    return configs


def resolve_child_path(project_path: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project_path / path
    return path.resolve()


def run_git(project_path: Path, args: list[str]) -> tuple[str | None, str | None]:
    command = ["git", "-C", str(project_path), *args]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)

    if completed.returncode != 0:
        return None, completed.stderr.strip() or completed.stdout.strip() or f"git exited {completed.returncode}"
    return completed.stdout.strip(), None


def collect_git_facts(project_path: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "available": False,
        "branch": None,
        "dirty": None,
        "remote_tracking": None,
        "commit": None,
        "errors": [],
    }

    inside, error = run_git(project_path, ["rev-parse", "--is-inside-work-tree"])
    if error or inside != "true":
        if error and "not a git repository" not in error:
            facts["errors"].append(error)
        return facts

    facts["available"] = True

    branch, error = run_git(project_path, ["branch", "--show-current"])
    if error:
        facts["errors"].append(error)
    facts["branch"] = branch or None

    commit, error = run_git(project_path, ["rev-parse", "--short", "HEAD"])
    if error:
        facts["errors"].append(error)
    facts["commit"] = commit or None

    status, error = run_git(project_path, ["status", "--short"])
    if error:
        facts["errors"].append(error)
    else:
        facts["dirty"] = bool(status)

    upstream, error = run_git(project_path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if error is None:
        facts["remote_tracking"] = upstream or None

    return facts


def scan_project(config: ProjectConfig, scan_time: datetime) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": config.name,
        "path": str(config.path),
        "status_file": str(config.status_file),
        "detail_file": str(config.detail_file),
        "declared": None,
        "derived_status": "invalid_status",
        "derived_reasons": [],
        "validation_errors": [],
        "git": None,
    }

    if not config.path.exists():
        entry["derived_status"] = "missing_project"
        entry["derived_reasons"].append("Project path does not exist.")
        return entry

    entry["git"] = collect_git_facts(config.path)

    if not config.status_file.exists():
        entry["derived_status"] = "missing_status"
        entry["derived_reasons"].append("Status file does not exist.")
        return entry

    payload, errors = validate_status_file(config.status_file)
    if errors:
        entry["derived_status"] = "invalid_status"
        entry["validation_errors"] = errors
        entry["derived_reasons"].append("Status file failed validation.")
        return entry

    assert payload is not None
    entry["declared"] = extract_declared_fields(payload)
    derived_status, reasons = derive_status(payload, entry["git"], scan_time)
    entry["derived_status"] = derived_status
    entry["derived_reasons"] = reasons
    return entry


def extract_declared_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": payload.get("name"),
        "path": payload.get("path"),
        "last_updated": payload.get("last_updated"),
        "phase": payload.get("phase"),
        "health": payload.get("health"),
        "status_confidence": payload.get("status_confidence"),
        "status_source": payload.get("status_source"),
        "current_goal": payload.get("current_goal"),
        "latest_summary": payload.get("latest_summary"),
        "next_action": payload.get("next_action"),
        "git": payload.get("git"),
        "verification": payload.get("verification"),
        "attention": payload.get("attention"),
    }


def derive_status(payload: dict[str, Any], git_facts: dict[str, Any] | None, scan_time: datetime) -> tuple[str, list[str]]:
    reasons: list[str] = []
    health = payload["health"]
    verification_status = payload["verification"]["status"]

    last_updated = parse_iso_datetime(payload["last_updated"])
    if last_updated.tzinfo is None:
        last_updated = last_updated.astimezone()
    if scan_time - last_updated > timedelta(hours=24):
        return "stale", ["last_updated is older than 24 hours."]

    if health == "blocked":
        return "blocked", ["Declared health is blocked."]

    if verification_status == "failed":
        return "needs_attention", ["Verification status is failed."]

    if git_facts and git_facts.get("available"):
        declared_git = payload.get("git", {})
        if git_facts.get("dirty") is True and declared_git.get("dirty") is False:
            reasons.append("Observed git state is dirty but declared git.dirty is false.")
        for key in ["branch", "commit", "remote_tracking"]:
            observed = git_facts.get(key)
            declared = declared_git.get(key)
            if observed is not None and declared not in {None, "", observed}:
                reasons.append(f"Observed git {key} differs from declared git.{key}.")
        if reasons:
            return "needs_attention", reasons

    return health, reasons


def write_state(entries: list[dict[str, Any]], scan_timestamp: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scan_timestamp": scan_timestamp,
        "repo_root": str(REPO_ROOT),
        "projects": entries,
    }
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_report(entries: list[dict[str, Any]], scan_timestamp: str) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# OctoPulse Latest Report",
        "",
        f"Scan timestamp: `{scan_timestamp}`",
        "",
    ]

    for status, title in GROUP_ORDER:
        group = [entry for entry in entries if entry["derived_status"] == status]
        lines.append(f"## {title}")
        lines.append("")
        if not group:
            lines.append("_No projects._")
            lines.append("")
            continue
        for entry in group:
            lines.extend(render_report_entry(entry))
            lines.append("")

    REPORT_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def render_report_entry(entry: dict[str, Any]) -> list[str]:
    declared = entry.get("declared") or {}
    git = entry.get("git") or {}
    declared_git = declared.get("git") or {}
    verification = declared.get("verification") or {}
    attention = declared.get("attention") or []

    lines = [
        f"### {entry['name']}",
        "",
        f"- Derived status: `{entry['derived_status']}`",
        f"- Declared health: `{declared.get('health', 'unknown')}`",
        f"- Current goal: {declared.get('current_goal', 'unknown')}",
        f"- Latest summary: {declared.get('latest_summary', 'unknown')}",
        f"- Next action: {declared.get('next_action', 'unknown')}",
        f"- Last updated: `{declared.get('last_updated', 'unknown')}`",
        (
            "- Git: "
            f"branch `{git.get('branch') or declared_git.get('branch') or 'unknown'}`, "
            f"dirty `{format_bool(git.get('dirty', declared_git.get('dirty')))}`, "
            f"commit `{git.get('commit') or declared_git.get('commit') or 'unknown'}`, "
            f"tracking `{git.get('remote_tracking') or declared_git.get('remote_tracking') or 'none'}`"
        ),
        f"- Verification: `{verification.get('status', 'unknown')}`",
    ]

    if attention:
        lines.append(f"- Attention: {', '.join(attention)}")
    else:
        lines.append("- Attention: none")

    if entry.get("derived_reasons"):
        lines.append(f"- Reason: {'; '.join(entry['derived_reasons'])}")
    if entry.get("validation_errors"):
        lines.append(f"- Validation errors: {'; '.join(entry['validation_errors'])}")

    return lines


def write_dashboard(entries: list[dict[str, Any]], scan_timestamp: str) -> None:
    DASHBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    cards = []
    for status, title in GROUP_ORDER:
        group = [entry for entry in entries if entry["derived_status"] == status]
        cards.append(f"<section class=\"group\"><h2>{html.escape(title)}</h2>")
        if not group:
            cards.append("<p class=\"empty\">No projects.</p>")
        else:
            for entry in group:
                cards.append(render_dashboard_card(entry))
        cards.append("</section>")

    content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OctoPulse Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --ink: #222831;
      --muted: #68707d;
      --line: #d9ded8;
      --panel: #ffffff;
      --accent: #0f766e;
      --attention: #b45309;
      --blocked: #b91c1c;
      --stable: #2563eb;
      --stale: #64748b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      background: #ffffff;
      padding: 24px clamp(16px, 4vw, 48px);
    }}
    h1 {{
      margin: 0 0 4px;
      font-size: clamp(28px, 4vw, 42px);
      line-height: 1.1;
      letter-spacing: 0;
    }}
    .timestamp {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }}
    main {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr));
      gap: 18px;
      padding: 24px clamp(16px, 4vw, 48px) 40px;
    }}
    .group {{
      min-width: 0;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 16px;
      letter-spacing: 0;
    }}
    .empty {{
      margin: 0;
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 14px;
      background: rgba(255, 255, 255, 0.5);
    }}
    .project {{
      margin: 0 0 12px;
      padding: 14px;
      border: 1px solid var(--line);
      border-left: 4px solid var(--accent);
      border-radius: 8px;
      background: var(--panel);
    }}
    .status-blocked {{ border-left-color: var(--blocked); }}
    .status-needs_attention {{ border-left-color: var(--attention); }}
    .status-stable {{ border-left-color: var(--stable); }}
    .status-stale,
    .status-missing_status,
    .status-missing_project,
    .status-invalid_status {{ border-left-color: var(--stale); }}
    .project h3 {{
      margin: 0 0 8px;
      font-size: 18px;
      letter-spacing: 0;
    }}
    dl {{
      display: grid;
      grid-template-columns: 110px minmax(0, 1fr);
      gap: 6px 10px;
      margin: 0;
    }}
    dt {{
      color: var(--muted);
    }}
    dd {{
      margin: 0;
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.92em;
    }}
  </style>
</head>
<body>
  <header>
    <h1>OctoPulse</h1>
    <p class="timestamp">Scan timestamp: <code>{html.escape(scan_timestamp)}</code></p>
  </header>
  <main>
    {''.join(cards)}
  </main>
</body>
</html>
"""
    DASHBOARD_FILE.write_text(content, encoding="utf-8")


def render_dashboard_card(entry: dict[str, Any]) -> str:
    declared = entry.get("declared") or {}
    git = entry.get("git") or {}
    declared_git = declared.get("git") or {}
    verification = declared.get("verification") or {}
    attention = declared.get("attention") or []
    reason = "; ".join(entry.get("derived_reasons") or entry.get("validation_errors") or [])

    rows = [
        ("Status", entry["derived_status"]),
        ("Health", declared.get("health", "unknown")),
        ("Goal", declared.get("current_goal", "unknown")),
        ("Summary", declared.get("latest_summary", "unknown")),
        ("Next", declared.get("next_action", "unknown")),
        ("Updated", declared.get("last_updated", "unknown")),
        ("Git", format_git_summary(git, declared_git)),
        ("Verify", verification.get("status", "unknown")),
        ("Attention", ", ".join(attention) if attention else "none"),
    ]
    if reason:
        rows.append(("Reason", reason))

    body = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>" for label, value in rows
    )
    css_status = html.escape(entry["derived_status"])
    title = html.escape(entry["name"])
    return f"<article class=\"project status-{css_status}\"><h3>{title}</h3><dl>{body}</dl></article>"


def format_git_summary(git: dict[str, Any], declared_git: dict[str, Any]) -> str:
    branch = git.get("branch") or declared_git.get("branch") or "unknown"
    dirty = format_bool(git.get("dirty", declared_git.get("dirty")))
    commit = git.get("commit") or declared_git.get("commit") or "unknown"
    tracking = git.get("remote_tracking") or declared_git.get("remote_tracking") or "none"
    return f"{branch} / dirty {dirty} / {commit} / {tracking}"


def format_bool(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan OctoPulse project status pulses.")
    parser.add_argument(
        "--projects",
        type=Path,
        default=DEFAULT_PROJECTS_FILE,
        help="Path to projects.yaml. Defaults to the OctoPulse repo root projects.yaml.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    projects_file = resolve_path(REPO_ROOT, str(args.projects))

    try:
        configs = load_project_configs(projects_file)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    scan_time = now_local()
    scan_timestamp = scan_time.isoformat(timespec="seconds")
    entries = [scan_project(config, scan_time) for config in configs]

    write_state(entries, scan_timestamp)
    write_report(entries, scan_timestamp)
    write_dashboard(entries, scan_timestamp)

    print(f"scanned {len(entries)} project(s)")
    print(f"wrote {STATE_FILE.relative_to(REPO_ROOT)}")
    print(f"wrote {REPORT_FILE.relative_to(REPO_ROOT)}")
    print(f"wrote {DASHBOARD_FILE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
