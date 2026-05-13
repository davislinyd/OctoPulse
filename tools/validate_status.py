#!/usr/bin/env python3
"""Validate one OctoPulse project status pulse."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PHASES = {"planning", "implementation", "verification", "maintenance", "paused"}
HEALTH_VALUES = {"active", "stable", "needs_attention", "blocked", "stale"}
CONFIDENCE_VALUES = {"high", "medium", "low"}
STATUS_SOURCES = {"agent_reported", "scanner_verified", "manual"}
VERIFICATION_VALUES = {"passed", "failed", "not_run", "partial"}

REQUIRED_TOP_LEVEL = [
    "name",
    "path",
    "last_updated",
    "phase",
    "health",
    "status_confidence",
    "status_source",
    "current_goal",
    "latest_summary",
    "next_action",
    "git",
    "verification",
    "attention",
]
REQUIRED_GIT = ["branch", "dirty", "remote_tracking", "commit"]
REQUIRED_VERIFICATION = ["status", "last_commands", "last_verified_at"]


def parse_iso_datetime(value: str) -> datetime:
    """Parse ISO 8601 timestamps with a small compatibility shim for Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_status(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, [f"{path}: file does not exist"]
    except json.JSONDecodeError as exc:
        return None, [f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"]
    except OSError as exc:
        return None, [f"{path}: cannot read file: {exc}"]

    if not isinstance(data, dict):
        return None, [f"{path}: root value must be a JSON object"]
    return data, []


def validate_status_payload(payload: dict[str, Any], source: str = "status payload") -> list[str]:
    errors: list[str] = []

    for field in REQUIRED_TOP_LEVEL:
        if field not in payload:
            errors.append(f"{source}: missing required field `{field}`")

    if errors:
        return errors

    for field in [
        "name",
        "path",
        "last_updated",
        "phase",
        "health",
        "status_confidence",
        "status_source",
        "current_goal",
        "latest_summary",
        "next_action",
    ]:
        if not isinstance(payload.get(field), str):
            errors.append(f"{source}: `{field}` must be a string")

    if isinstance(payload.get("last_updated"), str):
        try:
            parse_iso_datetime(payload["last_updated"])
        except ValueError:
            errors.append(f"{source}: `last_updated` must be a valid ISO 8601 timestamp")

    _validate_enum(errors, source, payload, "phase", PHASES)
    _validate_enum(errors, source, payload, "health", HEALTH_VALUES)
    _validate_enum(errors, source, payload, "status_confidence", CONFIDENCE_VALUES)
    _validate_enum(errors, source, payload, "status_source", STATUS_SOURCES)

    git = payload.get("git")
    if not isinstance(git, dict):
        errors.append(f"{source}: `git` must be an object")
    else:
        _validate_required_object(errors, source, "git", git, REQUIRED_GIT)
        if not isinstance(git.get("branch"), str):
            errors.append(f"{source}: `git.branch` must be a string")
        if not isinstance(git.get("dirty"), bool):
            errors.append(f"{source}: `git.dirty` must be a boolean")
        if git.get("remote_tracking") is not None and not isinstance(git.get("remote_tracking"), str):
            errors.append(f"{source}: `git.remote_tracking` must be a string or null")
        if not isinstance(git.get("commit"), str):
            errors.append(f"{source}: `git.commit` must be a string")

    verification = payload.get("verification")
    if not isinstance(verification, dict):
        errors.append(f"{source}: `verification` must be an object")
    else:
        _validate_required_object(errors, source, "verification", verification, REQUIRED_VERIFICATION)
        _validate_enum(errors, source, verification, "status", VERIFICATION_VALUES, prefix="verification.")
        if not isinstance(verification.get("last_commands"), list):
            errors.append(f"{source}: `verification.last_commands` must be an array")
        else:
            for index, command in enumerate(verification["last_commands"]):
                if not isinstance(command, str):
                    errors.append(f"{source}: `verification.last_commands[{index}]` must be a string")
        last_verified_at = verification.get("last_verified_at")
        if last_verified_at is not None:
            if not isinstance(last_verified_at, str):
                errors.append(f"{source}: `verification.last_verified_at` must be a string or null")
            else:
                try:
                    parse_iso_datetime(last_verified_at)
                except ValueError:
                    errors.append(
                        f"{source}: `verification.last_verified_at` must be a valid ISO 8601 timestamp or null"
                    )

    attention = payload.get("attention")
    if not isinstance(attention, list):
        errors.append(f"{source}: `attention` must be an array")
    else:
        for index, item in enumerate(attention):
            if not isinstance(item, str):
                errors.append(f"{source}: `attention[{index}]` must be a string")

    return errors


def _validate_required_object(
    errors: list[str], source: str, object_name: str, payload: dict[str, Any], required_fields: list[str]
) -> None:
    for field in required_fields:
        if field not in payload:
            errors.append(f"{source}: missing required field `{object_name}.{field}`")


def _validate_enum(
    errors: list[str],
    source: str,
    payload: dict[str, Any],
    field: str,
    allowed: set[str],
    prefix: str = "",
) -> None:
    value = payload.get(field)
    if isinstance(value, str) and value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        errors.append(f"{source}: `{prefix}{field}` must be one of: {allowed_values}")


def validate_status_file(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    payload, load_errors = load_status(path)
    if load_errors:
        return payload, load_errors
    assert payload is not None
    return payload, validate_status_payload(payload, str(path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate one OctoPulse .ai/status.json file.")
    parser.add_argument("status_file", type=Path, help="Path to the status JSON file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _, errors = validate_status_file(args.status_file)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print("validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
