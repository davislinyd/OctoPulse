"""Dependency-free core for the OctoPulse v2 CLI."""

from __future__ import annotations

import hashlib
import html
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


VERSION = 2
RELEASE_VERSION = "2.2.0"
MARKER_NAME = ".otcopulse"
MAX_MARKER_BYTES = 4096
PHASES = {"planning", "implementation", "verification", "maintenance", "paused"}
HEALTH_VALUES = {"active", "stable", "needs_attention", "blocked", "stale"}
VERIFICATION_VALUES = {"passed", "failed", "not_run", "partial"}
SKIP_DIRECTORIES = {".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", ".venv", "venv", "__pycache__"}


def octopulse_home() -> Path:
    """Return the user-owned OctoPulse data directory without creating it."""
    explicit = os.environ.get("OCTOPULSE_HOME")
    if explicit:
        return Path(explicit).expanduser()
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "octopulse"


def config_path() -> Path:
    return octopulse_home() / "config.json"


def cache_path() -> Path:
    return octopulse_home() / "cache.json"


def default_report_dir() -> Path:
    return octopulse_home() / "reports"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"{path}: file does not exist"
    except UnicodeDecodeError:
        return None, f"{path}: must be UTF-8"
    except json.JSONDecodeError as exc:
        return None, f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
    except OSError as exc:
        return None, f"{path}: cannot read file: {exc}"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"schema_version": VERSION, "roots": []}
    payload, error = read_json(path)
    if error or not isinstance(payload, dict):
        raise ValueError(error or f"{path}: root must be an object")
    roots = payload.get("roots", [])
    if not isinstance(roots, list) or not all(isinstance(root, str) for root in roots):
        raise ValueError(f"{path}: `roots` must be an array of paths")
    return {"schema_version": VERSION, "roots": roots}


def save_config(config: dict[str, Any]) -> None:
    roots = sorted({str(Path(root).expanduser().resolve()) for root in config.get("roots", [])})
    write_json(config_path(), {"schema_version": VERSION, "roots": roots})


def add_root(root: Path) -> bool:
    config = load_config()
    normalized = str(root.resolve())
    if normalized in config["roots"]:
        return False
    config["roots"].append(normalized)
    save_config(config)
    return True


def remove_root(root: Path) -> bool:
    config = load_config()
    normalized = str(root.resolve())
    roots = [item for item in config["roots"] if item != normalized]
    if len(roots) == len(config["roots"]):
        return False
    config["roots"] = roots
    save_config(config)
    return True


def run_git(directory: Path, args: list[str]) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if result.returncode:
        return None, result.stderr.strip() or result.stdout.strip() or f"git exited {result.returncode}"
    return result.stdout.strip(), None


def git_root(directory: Path) -> Path | None:
    value, error = run_git(directory, ["rev-parse", "--show-toplevel"])
    return Path(value).resolve() if value and error is None else None


def git_facts(project_root: Path) -> dict[str, Any]:
    inside, error = run_git(project_root, ["rev-parse", "--is-inside-work-tree"])
    if error or inside != "true":
        return {"available": False, "branch": None, "commit": None, "dirty": None}
    branch, _ = run_git(project_root, ["branch", "--show-current"])
    commit, _ = run_git(project_root, ["rev-parse", "--short", "HEAD"])
    porcelain, _ = run_git(project_root, ["status", "--porcelain"])
    return {"available": True, "branch": branch or None, "commit": commit or None, "dirty": bool(porcelain)}


def validate_marker_payload(payload: Any, source: str = "marker") -> list[str]:
    if not isinstance(payload, dict):
        return [f"{source}: root value must be an object"]
    required = [
        "schema_version", "name", "last_updated", "phase", "health", "goal", "summary", "next_action", "verification", "attention",
    ]
    errors = [f"{source}: missing required field `{field}`" for field in required if field not in payload]
    if errors:
        return errors
    allowed = set(required)
    for field in payload:
        if field not in allowed:
            errors.append(f"{source}: unknown field `{field}`")
    if payload["schema_version"] != VERSION:
        errors.append(f"{source}: `schema_version` must be {VERSION}")
    for field in ["name", "last_updated", "phase", "health", "goal", "summary", "next_action"]:
        if not isinstance(payload[field], str):
            errors.append(f"{source}: `{field}` must be a string")
    if isinstance(payload.get("last_updated"), str):
        try:
            datetime.fromisoformat(payload["last_updated"].replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"{source}: `last_updated` must be ISO 8601")
    if payload.get("phase") not in PHASES:
        errors.append(f"{source}: `phase` must be one of: {', '.join(sorted(PHASES))}")
    if payload.get("health") not in HEALTH_VALUES:
        errors.append(f"{source}: `health` must be one of: {', '.join(sorted(HEALTH_VALUES))}")
    limits = {"name": 160, "goal": 480, "summary": 1600, "next_action": 480}
    for field, limit in limits.items():
        if isinstance(payload.get(field), str) and len(payload[field]) > limit:
            errors.append(f"{source}: `{field}` exceeds {limit} characters")
    verification = payload.get("verification")
    if not isinstance(verification, dict):
        errors.append(f"{source}: `verification` must be an object")
    else:
        allowed_verification = {"status", "last_command", "last_verified_at"}
        for field in verification:
            if field not in allowed_verification:
                errors.append(f"{source}: unknown field `verification.{field}`")
        for field in ["status", "last_command", "last_verified_at"]:
            if field not in verification:
                errors.append(f"{source}: missing required field `verification.{field}`")
        if verification.get("status") not in VERIFICATION_VALUES:
            errors.append(f"{source}: `verification.status` must be valid")
        if not isinstance(verification.get("last_command"), str):
            errors.append(f"{source}: `verification.last_command` must be a string")
        verified = verification.get("last_verified_at")
        if verified is not None and not isinstance(verified, str):
            errors.append(f"{source}: `verification.last_verified_at` must be a string or null")
        elif isinstance(verified, str):
            try:
                datetime.fromisoformat(verified.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{source}: `verification.last_verified_at` must be ISO 8601 or null")
    attention = payload.get("attention")
    if not isinstance(attention, list) or not all(isinstance(item, str) for item in attention):
        errors.append(f"{source}: `attention` must be an array of strings")
    elif len(attention) > 8:
        errors.append(f"{source}: `attention` cannot contain more than 8 items")
    try:
        encoded_size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
    except (TypeError, ValueError):
        encoded_size = MAX_MARKER_BYTES + 1
    if encoded_size > MAX_MARKER_BYTES:
        errors.append(f"{source}: marker exceeds {MAX_MARKER_BYTES} bytes")
    return errors


def inspect_marker(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"state": "missing", "path": str(path), "errors": []}
    if path.is_symlink() or not path.is_file():
        return {"state": "invalid", "path": str(path), "errors": ["marker must be a regular file"]}
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {"state": "invalid", "path": str(path), "errors": [str(exc)]}
    if size > MAX_MARKER_BYTES:
        return {"state": "invalid", "path": str(path), "errors": [f"marker exceeds {MAX_MARKER_BYTES} bytes"]}
    if size == 0:
        return {"state": "uninitialized", "path": str(path), "errors": []}
    payload, error = read_json(path)
    if error:
        return {"state": "invalid", "path": str(path), "errors": [error]}
    errors = validate_marker_payload(payload, str(path))
    return {"state": "valid" if not errors else "invalid", "path": str(path), "payload": payload if not errors else None, "errors": errors}


def marker_for(directory: Path) -> tuple[Path | None, Path | None]:
    root = git_root(directory)
    return root, root / MARKER_NAME if root else None


def context_for(directory: Path) -> dict[str, Any]:
    root, marker = marker_for(directory)
    config = load_config()
    if root is None or marker is None:
        return {"project_root": None, "marker": None, "state": "not_git_project", "registered": False, "errors": []}
    inspected = inspect_marker(marker)
    return {
        "project_root": str(root),
        "marker": str(marker),
        "state": inspected["state"],
        "registered": str(root) in config["roots"],
        "errors": inspected["errors"],
    }


def discover_markers(roots: Iterable[str]) -> tuple[list[Path], list[str]]:
    markers: list[Path] = []
    missing_roots: list[str] = []
    for raw_root in roots:
        root = Path(raw_root)
        if not root.is_dir():
            missing_roots.append(str(root))
            continue
        for current, directories, files in os.walk(root, topdown=True, followlinks=False):
            directories[:] = [name for name in directories if name not in SKIP_DIRECTORIES and not (Path(current) / name).is_symlink()]
            if MARKER_NAME in files:
                marker = Path(current) / MARKER_NAME
                if not marker.is_symlink():
                    markers.append(marker)
    return sorted(set(markers)), missing_roots


def scan_projects() -> tuple[list[dict[str, Any]], list[str], list[str]]:
    config = load_config()
    markers, missing_roots = discover_markers(config["roots"])
    entries: list[dict[str, Any]] = []
    reads: list[str] = []
    for marker in markers:
        reads.append(str(marker))
        inspection = inspect_marker(marker)
        root = git_root(marker.parent) or marker.parent
        if root != marker.parent:
            inspection = {
                "state": "invalid",
                "errors": ["marker must be located at the Git project root"],
            }
        entry: dict[str, Any] = {
            "path": str(root),
            "marker": str(marker),
            "state": inspection["state"],
            "errors": inspection["errors"],
            "status": inspection.get("payload"),
            "git": git_facts(root),
        }
        entries.append(entry)
    for root in missing_roots:
        entries.append({"path": root, "marker": None, "state": "missing_root", "errors": ["configured root does not exist"], "status": None, "git": None})
    return entries, reads, missing_roots


def fingerprint(entries: list[dict[str, Any]]) -> str:
    encoded = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_cache() -> dict[str, Any]:
    payload, error = read_json(cache_path())
    return payload if not error and isinstance(payload, dict) else {}


def report_markdown(entries: list[dict[str, Any]]) -> str:
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        state = entry["state"]
        if state == "valid":
            state = entry["status"]["health"]
        groups.setdefault(state, []).append(entry)
    lines = ["# OctoPulse Report", ""]
    for state in ["blocked", "needs_attention", "active", "stable", "stale", "uninitialized", "invalid", "missing_root"]:
        values = groups.get(state, [])
        if not values:
            continue
        lines.extend([f"## {state.replace('_', ' ').title()} ({len(values)})", ""])
        for entry in values:
            status = entry.get("status") or {}
            lines.append(f"- **{status.get('name', Path(entry['path']).name)}** — `{entry['path']}`")
            if status:
                lines.append(f"  - Goal: {status['goal']}")
                lines.append(f"  - Summary: {status['summary']}")
                lines.append(f"  - Next: {status['next_action']}")
            else:
                lines.append(f"  - {', '.join(entry['errors']) or entry['state']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def report_html(entries: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for entry in entries:
        status = entry.get("status") or {}
        state = status.get("health", entry["state"])
        rows.append(
            "<tr>"
            f"<td>{html.escape(status.get('name', Path(entry['path']).name))}</td>"
            f"<td>{html.escape(state)}</td>"
            f"<td>{html.escape(status.get('goal', ', '.join(entry['errors'])))}</td>"
            f"<td>{html.escape(status.get('next_action', ''))}</td>"
            "</tr>"
        )
    return """<!doctype html>
<html lang=\"en\"><meta charset=\"utf-8\"><title>OctoPulse Report</title>
<style>body{font-family:system-ui;margin:2rem;color:#172033}table{border-collapse:collapse;width:100%}th,td{padding:.7rem;border-bottom:1px solid #dbe2ea;text-align:left}th{background:#f4f7fa}</style>
<h1>OctoPulse Report</h1><table><thead><tr><th>Project</th><th>Status</th><th>Goal</th><th>Next action</th></tr></thead><tbody>""" + "".join(rows) + "</tbody></table></html>\n"


def write_report(entries: list[dict[str, Any]], output: Path, report_format: str) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    written = [output / "projects.json"]
    write_json(written[0], {"schema_version": VERSION, "projects": entries})
    if report_format in {"markdown", "both"}:
        path = output / "latest.md"
        path.write_text(report_markdown(entries), encoding="utf-8")
        written.append(path)
    if report_format in {"html", "both"}:
        path = output / "index.html"
        path.write_text(report_html(entries), encoding="utf-8")
        written.append(path)
    return written


def archive_marker(root: Path, reason: str) -> dict[str, Any]:
    """Return a source-free archival pulse for a retired project."""
    return {
        "schema_version": VERSION,
        "name": root.name,
        "last_updated": now_iso(),
        "phase": "paused",
        "health": "stale",
        "goal": "Keep this retired project visible without active work.",
        "summary": reason,
        "next_action": "Resume only after an explicit owner decision.",
        "verification": {
            "status": "not_run",
            "last_command": "",
            "last_verified_at": None,
        },
        "attention": [],
    }
