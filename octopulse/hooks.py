"""Codex hook helpers with strict v2-only inputs and outputs."""

from __future__ import annotations

import json
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any


V1_COMMAND_MARKERS = ("octopulse_codex_hook.py", "octopulse-status")
V2_COMMAND_MARKERS = ("octopulse hook codex-session-start", "octopulse hook codex-stop")


def read_payload(stream: Any) -> dict[str, Any] | None:
    """Read one hook JSON object; callers must only consume approved fields."""
    try:
        payload = json.load(stream)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def codex_context_message() -> str:
    return "OctoPulse: use the global skill; read only .otcopulse and lightweight Git facts."


def session_start_output() -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": codex_context_message(),
            }
        },
        ensure_ascii=False,
    )


def _is_handler(command: Any, markers: tuple[str, ...]) -> bool:
    return isinstance(command, str) and any(marker in command for marker in markers)


def _filtered_groups(groups: Any, markers: tuple[str, ...]) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(groups, list):
        return [], 0
    filtered: list[dict[str, Any]] = []
    removed = 0
    for group in groups:
        if not isinstance(group, dict):
            filtered.append(group)
            continue
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            filtered.append(group)
            continue
        retained = [handler for handler in handlers if not (isinstance(handler, dict) and _is_handler(handler.get("command"), markers))]
        removed += len(handlers) - len(retained)
        if retained:
            filtered.append({**group, "hooks": retained})
    return filtered, removed


def _remove_matching(config: dict[str, Any], event: str, markers: tuple[str, ...]) -> int:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    groups, removed = _filtered_groups(hooks.get(event), markers)
    if groups:
        hooks[event] = groups
    else:
        hooks.pop(event, None)
    if not hooks:
        config.pop("hooks", None)
    return removed


def _add_v2_handlers(config: dict[str, Any], command: str) -> None:
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks.json: `hooks` must be an object")
    quoted = shlex.quote(command)
    hooks.setdefault("SessionStart", []).append(
        {
            "matcher": "startup|resume",
            "hooks": [
                {
                    "type": "command",
                    "command": f"{quoted} hook codex-session-start",
                    "timeout": 5,
                    "statusMessage": "Loading OctoPulse reminder",
                }
            ],
        }
    )
    hooks.setdefault("Stop", []).append(
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f"{quoted} hook codex-stop",
                    "timeout": 5,
                    "statusMessage": "Refreshing OctoPulse reports",
                }
            ],
        }
    )


def _load_config(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {}, False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid hooks JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: hooks JSON root must be an object")
    return payload, True


def _backup_path(path: Path) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    return path.with_name(f"{path.name}.octopulse-v1-backup-{stamp}")


def install_codex_hooks(path: Path, command: str) -> dict[str, Any]:
    config, existed = _load_config(path)
    original = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    removed_v1 = _remove_matching(config, "UserPromptSubmit", V1_COMMAND_MARKERS)
    _remove_matching(config, "SessionStart", V2_COMMAND_MARKERS)
    _remove_matching(config, "Stop", V2_COMMAND_MARKERS)
    _add_v2_handlers(config, command)
    backup = None
    if existed and removed_v1:
        backup = _backup_path(path)
        backup.write_bytes(path.read_bytes())
    changed = original != json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    return {"hooks_file": str(path), "backup": str(backup) if backup else None, "removed_v1_handlers": removed_v1, "changed": changed}


def remove_codex_hooks(path: Path) -> dict[str, Any]:
    config, existed = _load_config(path)
    if not existed:
        return {"hooks_file": str(path), "removed_v2_handlers": 0}
    removed = _remove_matching(config, "SessionStart", V2_COMMAND_MARKERS)
    removed += _remove_matching(config, "Stop", V2_COMMAND_MARKERS)
    if removed:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    return {"hooks_file": str(path), "removed_v2_handlers": removed, "changed": bool(removed)}
