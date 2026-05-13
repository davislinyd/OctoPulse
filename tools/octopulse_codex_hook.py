#!/usr/bin/env python3
"""Codex hook helper for injecting OctoPulse status reminders.

This script is intended for Codex `UserPromptSubmit` hooks. It reads the hook
payload from stdin and writes a small JSON response with `additionalContext`
when the current working directory belongs to an OctoPulse-managed project.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


OCTOPULSE_ROOT = Path("/Users/lindav/git/OctoPulse").resolve()
LOCAL_REPO_ROOT = Path("/Users/lindav/git").resolve()
PROJECTS_FILE = OCTOPULSE_ROOT / "projects.yaml"
STATUS_SCHEMA = OCTOPULSE_ROOT / "schemas" / "status.schema.json"
VALIDATOR = OCTOPULSE_ROOT / "tools" / "validate_status.py"
SCANNER = OCTOPULSE_ROOT / "tools" / "scan_projects.py"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return emit({})

    if not isinstance(payload, dict):
        return emit({})

    cwd_value = payload.get("cwd")
    if not isinstance(cwd_value, str):
        return emit({})

    cwd = resolve_path(cwd_value)
    if cwd is None or not is_relative_to(cwd, LOCAL_REPO_ROOT):
        return emit({})

    managed_projects = load_projects()
    project = find_managed_project(cwd, managed_projects)

    if project is None:
        project = find_project_with_status_files(cwd)
        if project is None:
            return emit({})

    if project["path"] == OCTOPULSE_ROOT:
        return emit({})

    context = build_context(project)
    return emit({"additionalContext": context})


def resolve_path(value: str) -> Path | None:
    try:
        return Path(value).expanduser().resolve()
    except OSError:
        return None


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def load_projects() -> list[dict[str, Any]]:
    if not PROJECTS_FILE.exists():
        return []

    projects: list[dict[str, Any]] = []
    current: dict[str, str] | None = None

    try:
        lines = PROJECTS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "projects:":
            continue

        if line.startswith("  - "):
            if current is not None:
                projects.append(normalize_project(current))
            current = {}
            remainder = line[4:].strip()
            if remainder:
                key, value = parse_key_value(remainder)
                if key:
                    current[key] = value
            continue

        if line.startswith("    ") and current is not None:
            key, value = parse_key_value(stripped)
            if key:
                current[key] = value

    if current is not None:
        projects.append(normalize_project(current))

    return [project for project in projects if project.get("path") is not None]


def parse_key_value(text: str) -> tuple[str | None, str]:
    if ":" not in text:
        return None, ""
    key, value = text.split(":", 1)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key.strip(), value


def normalize_project(raw: dict[str, str]) -> dict[str, Any]:
    raw_path = raw.get("path")
    project_path = resolve_project_path(raw_path) if raw_path else None
    status_file = raw.get("status_file", ".ai/status.json")
    detail_file = raw.get("detail_file", "PROJECT_STATUS.md")

    if project_path is None:
        return {"name": raw.get("name", "Unknown Project"), "path": None}

    return {
        "name": raw.get("name", project_path.name),
        "path": project_path,
        "status_file": resolve_child_path(project_path, status_file),
        "detail_file": resolve_child_path(project_path, detail_file),
        "managed": True,
    }


def resolve_project_path(value: str) -> Path | None:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = OCTOPULSE_ROOT / path
    return resolve_path(str(path))


def resolve_child_path(project_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_path / path
    return path.resolve()


def find_managed_project(cwd: Path, projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [
        project
        for project in projects
        if isinstance(project.get("path"), Path) and is_relative_to(cwd, project["path"])
    ]
    if not matches:
        return None
    return max(matches, key=lambda project: len(project["path"].parts))


def find_project_with_status_files(cwd: Path) -> dict[str, Any] | None:
    for candidate in [cwd, *cwd.parents]:
        if not is_relative_to(candidate, LOCAL_REPO_ROOT):
            break
        status_file = candidate / ".ai" / "status.json"
        detail_file = candidate / "PROJECT_STATUS.md"
        if status_file.exists() or detail_file.exists():
            return {
                "name": candidate.name,
                "path": candidate,
                "status_file": status_file,
                "detail_file": detail_file,
                "managed": False,
            }
    return None


def build_context(project: dict[str, Any]) -> str:
    status_file = project["status_file"]
    detail_file = project["detail_file"]
    managed = "yes" if project.get("managed") else "not listed, but status files exist"

    return "\n".join(
        [
            "OctoPulse reminder:",
            f"- Project: {project['name']}",
            f"- Managed by OctoPulse: {managed}",
            "- Use the global `octopulse-status` skill when onboarding or updating project status.",
            f"- Project status files: `{detail_file}` and `{status_file}`",
            "- For non-trivial work, update the project-local status files before finishing.",
            "- Keep `.ai/status.json` short, factual, machine-readable, and schema-compatible.",
            f"- Status schema: `{STATUS_SCHEMA}`",
            f"- Validate when practical: `python {VALIDATOR} {status_file}`",
            f"- Refresh central outputs when practical: `cd {OCTOPULSE_ROOT} && python {SCANNER}`",
            "- Do not write secrets, passwords, API keys, cookies, tokens, raw ticket dumps, raw logs, or private customer/user data into status files.",
            "- Do not directly edit OctoPulse central generated outputs from this project.",
        ]
    )


def emit(response: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
