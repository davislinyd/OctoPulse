"""Local trace journal built from Git history, AI transcripts, and the marker.

Only structured fields are kept: commit metadata, todo items, session counts, and edited
paths inside the project. Prompts, replies, tool output, diffs, and commands are never stored.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import core

REPORT_DIR_NAME = ".octopulse-reports"
JOURNAL_FILE = "journal.jsonl"
CURSOR_FILE = "journal-cursor.json"
MAX_EVENTS = 1000
RETENTION_DAYS = 180
MAX_EVENT_BYTES = 4096
INITIAL_GIT_COMMITS = 20
MAX_GIT_COMMITS = 50
MAX_COMMIT_TODOS = 5
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024
MAX_TRACKED = 50
MAX_SESSION_FILES = 12
MAX_TODO_ITEMS = 20
MAX_TEXT = 200
COMMIT_LINK_WINDOW = timedelta(minutes=10)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
KINDS = {"commit", "todo", "session", "todos", "next_action"}
DONE_STATUSES = {"completed", "deleted"}
EDIT_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
SESSION_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}")
CONVENTIONAL = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]{1,40})\))?(?P<breaking>!)?:\s")
TODO_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:TODO|FIXME|Follow-up)\s*:\s*(?P<text>.+)$", re.IGNORECASE)
GIT_COMMIT = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")
SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|\b[A-Fa-f0-9]{32,}\b|[A-Za-z0-9+=_-]{40,}"
)


def journal_path(project_root: Path) -> Path:
    return project_root / REPORT_DIR_NAME / JOURNAL_FILE


def cursor_path(project_root: Path) -> Path:
    return project_root / REPORT_DIR_NAME / CURSOR_FILE


def mask(value: Any, limit: int = MAX_TEXT) -> str:
    return SECRET.sub("[REDACTED]", " ".join(str(value).split()))[:limit]


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _sort_key(event: dict[str, Any]) -> datetime:
    return _time(event.get("at")) or EPOCH


def load_events(project_root: Path) -> list[dict[str, Any]]:
    path = journal_path(project_root)
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-MAX_EVENTS:]
    except OSError:
        return []
    cutoff = datetime.now().astimezone() - timedelta(days=RETENTION_DAYS)
    events: list[dict[str, Any]] = []
    for line in lines:
        if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or item.get("kind") not in KINDS:
            continue
        at = _time(item.get("at"))
        if at is None or at < cutoff:
            continue
        events.append(item)
    return events


def _encode(event: dict[str, Any]) -> str | None:
    """Return one bounded JSON line, dropping trailing list items when the line is too large."""
    event = dict(event)
    key = {"todos": "items", "session": "files"}.get(event["kind"])
    while True:
        line = json.dumps(event, ensure_ascii=False)
        if len(line.encode("utf-8")) <= MAX_EVENT_BYTES:
            return line
        if not key or not event.get(key):
            return None
        event[key] = event[key][:-1]


def _write_events(project_root: Path, events: list[dict[str, Any]]) -> None:
    lines = [line for line in (_encode(event) for event in sorted(events, key=_sort_key)[-MAX_EVENTS:]) if line]
    path = journal_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    temporary.replace(path)


def _ingest_git(project_root: Path, cursor: dict[str, Any], known: set[str]) -> list[dict[str, Any]]:
    head, error = core.run_git(project_root, ["rev-parse", "HEAD"])
    if error or not head or cursor.get("git_head") == head:
        return []
    last = cursor.get("git_head")
    revision = [f"--max-count={INITIAL_GIT_COMMITS}", head]
    if isinstance(last, str) and last and core.run_git(project_root, ["merge-base", "--is-ancestor", last, head])[1] is None:
        revision = [f"--max-count={MAX_GIT_COMMITS}", f"{last}..{head}"]
    output, error = core.run_git(project_root, ["log", "--date=iso-strict", "--numstat", "--format=%x1e%H%x1f%h%x1f%cd%x1f%s%x1f%b%x1d", *revision])
    cursor["git_head"] = head
    if error or not output:
        return []
    events: list[dict[str, Any]] = []
    for record in output.split("\x1e")[1:]:
        header, _, numstat = record.partition("\x1d")
        parts = header.split("\x1f", 4)
        if len(parts) != 5 or parts[0] in known:
            continue
        full, short, at, subject, body = parts
        insertions = deletions = files = 0
        for line in numstat.strip().splitlines():
            columns = line.split("\t", 2)
            if len(columns) != 3:
                continue
            files += 1
            insertions += int(columns[0]) if columns[0].isdigit() else 0
            deletions += int(columns[1]) if columns[1].isdigit() else 0
        match = CONVENTIONAL.match(subject)
        events.append(
            {
                "kind": "commit",
                "at": at,
                "commit": short,
                "commit_full": full,
                "subject": subject[:240],
                "type": match["type"] if match else None,
                "scope": match["scope"] if match else None,
                "breaking": bool(match and match["breaking"]) or "BREAKING CHANGE" in body,
                "insertions": insertions,
                "deletions": deletions,
                "files_changed": files,
            }
        )
        todos = [found["text"] for found in (TODO_LINE.match(line) for line in body.splitlines()) if found]
        events.extend({"kind": "todo", "source": "commit", "at": at, "commit": short, "text": mask(text)} for text in todos[:MAX_COMMIT_TODOS])
    return events


def _ingest_marker(project_root: Path, cursor: dict[str, Any]) -> list[dict[str, Any]]:
    inspection = core.inspect_marker(project_root / core.MARKER_NAME)
    if inspection["state"] != "valid":
        return []
    payload = inspection["payload"]
    current = payload.get("next_action") or ""
    previous = cursor.get("next_action")
    cursor["next_action"] = current
    if current == previous or current == core.DEFAULT_NEXT or not current.strip():
        return []
    return [{"kind": "next_action", "at": payload.get("last_updated") or core.now_iso(), "text": mask(current), "previous": mask(previous) if previous else None}]


def transcript_roots() -> list[Path]:
    home = Path.home()
    roots = [home / ".claude" / "projects", home / ".codex" / "sessions"]
    for variable, child in (("CLAUDE_CONFIG_DIR", "projects"), ("CODEX_HOME", "sessions")):
        if os.environ.get(variable):
            roots.append(Path(os.environ[variable]).expanduser() / child)
    return roots


def trusted_transcript(raw: Any) -> Path | None:
    """Accept only a regular, non-symlink transcript file inside a known AI tool directory."""
    if not isinstance(raw, str) or not raw or len(raw) > 1024:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        return None
    resolved = path.resolve()
    for root in transcript_roots():
        if root.is_dir() and resolved.is_relative_to(root.resolve()):
            return resolved
    return None


def _read_new_lines(path: Path, state: dict[str, Any]) -> list[str]:
    size = path.stat().st_size
    offset = state.get("offset") if isinstance(state.get("offset"), int) else 0
    if offset > size:
        offset = 0
    with path.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read(MAX_TRANSCRIPT_BYTES)
    end = chunk.rfind(b"\n")
    if end < 0:
        # A single line larger than the budget is skipped instead of blocking later lines.
        state["offset"] = offset + len(chunk) if len(chunk) >= MAX_TRANSCRIPT_BYTES else offset
        return []
    state["offset"] = offset + end + 1
    return chunk[: end + 1].decode("utf-8", "replace").splitlines()


def _touch(session: dict[str, Any], stamp: Any) -> None:
    at = _time(stamp)
    if at is None:
        return
    value = at.astimezone().isoformat(timespec="seconds")
    if not session["started_at"] or at < _time(session["started_at"]):
        session["started_at"] = value
    if not session["ended_at"] or at > _time(session["ended_at"]):
        session["ended_at"] = value


def _add_file(session: dict[str, Any], project_root: Path, raw: Any) -> None:
    if not isinstance(raw, str) or not raw or len(session["files"]) >= MAX_SESSION_FILES:
        return
    path = Path(raw)
    try:
        relative = (path if path.is_absolute() else project_root / path).resolve().relative_to(project_root).as_posix()
    except (OSError, ValueError):
        return
    if relative not in session["files"]:
        session["files"].append(relative[:240])


def _set_task(session: dict[str, Any], task_id: Any, text: Any = None, status: Any = None) -> None:
    key = str(task_id or "")
    if not key:
        return
    if status == "deleted":
        session["tasks"].pop(key, None)
        return
    if key not in session["tasks"] and len(session["tasks"]) >= MAX_TODO_ITEMS * 5:
        return
    task =session["tasks"].setdefault(key, {"text": "", "status": "pending"})
    if isinstance(text, str) and text.strip():
        task["text"] = mask(text)
    if isinstance(status, str) and status:
        task["status"] = status[:20]


def _replace_tasks(session: dict[str, Any], items: list[Any], text_key: str) -> None:
    session["tasks"] = {}
    for index, item in enumerate(items[:MAX_TODO_ITEMS]):
        if isinstance(item, dict):
            _set_task(session, index + 1, item.get(text_key), item.get("status") or "pending")


def _claude_line(item: dict[str, Any], session: dict[str, Any], project_root: Path, commit_times: list[datetime]) -> None:
    kind = item.get("type")
    message = item.get("message")
    if kind not in {"user", "assistant"} or not isinstance(message, dict):
        return
    _touch(session, item.get("timestamp"))
    content = message.get("content")
    if kind == "user":
        result = item.get("toolUseResult")
        if isinstance(result, dict) and isinstance(result.get("task"), dict):
            _set_task(session, result["task"].get("id"), result["task"].get("subject"))
        is_prompt = isinstance(content, str) or (isinstance(content, list) and any(isinstance(block, dict) and block.get("type") == "text" for block in content))
        if is_prompt and not item.get("isMeta"):
            session["turns"] += 1
        return
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        session["tool_calls"] += 1
        name = block.get("name")
        data = block.get("input") if isinstance(block.get("input"), dict) else {}
        if name in EDIT_TOOLS:
            _add_file(session, project_root, data.get(EDIT_TOOLS[name]))
        elif name == "Bash" and GIT_COMMIT.search(str(data.get("command", ""))):
            stamp = _time(item.get("timestamp"))
            if stamp:
                commit_times.append(stamp)
        elif name == "TaskUpdate":
            _set_task(session, data.get("taskId"), data.get("subject"), data.get("status"))
        elif name == "TodoWrite" and isinstance(data.get("todos"), list):
            _replace_tasks(session, data["todos"], "content")


def _codex_line(item: dict[str, Any], session: dict[str, Any], project_root: Path, commit_times: list[datetime]) -> None:
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return
    if item.get("type") == "response_item" and payload.get("type") in {"function_call", "custom_tool_call", "local_shell_call"}:
        _touch(session, item.get("timestamp"))
        session["tool_calls"] += 1
        if payload.get("name") == "update_plan":
            try:
                arguments = json.loads(payload.get("arguments") or "{}")
            except (TypeError, json.JSONDecodeError):
                return
            if isinstance(arguments, dict) and isinstance(arguments.get("plan"), list):
                _replace_tasks(session, arguments["plan"], "step")
        return
    record = payload.get("item")
    if item.get("type") != "event_msg" or payload.get("type") != "item_completed" or not isinstance(record, dict):
        return
    _touch(session, item.get("timestamp"))
    if record.get("type") == "UserMessage":
        session["turns"] += 1
    elif record.get("type") == "FileChange" and isinstance(record.get("changes"), dict):
        for path in record["changes"]:
            _add_file(session, project_root, path)
    elif record.get("type") == "CommandExecution" and record.get("exit_code") == 0:
        command = record.get("command")
        text = " ".join(part for part in command if isinstance(part, str)) if isinstance(command, list) else str(command or "")
        stamp = _time(item.get("timestamp"))
        if stamp and GIT_COMMIT.search(text):
            commit_times.append(stamp)


PARSERS: dict[str, Callable[[dict[str, Any], dict[str, Any], Path, list[datetime]], None]] = {"claude": _claude_line, "codex": _codex_line}


def _remember(mapping: dict[str, Any], key: str, value: Any) -> None:
    mapping.pop(key, None)
    mapping[key] = value
    while len(mapping) > MAX_TRACKED:
        mapping.pop(next(iter(mapping)))


def _ingest_transcript(project_root: Path, tool: str, payload: dict[str, Any], cursor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[datetime]]:
    parser = PARSERS.get(tool)
    session_id = payload.get("session_id")
    path = trusted_transcript(payload.get("transcript_path"))
    if parser is None or path is None or not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        return [], []
    transcripts = cursor.setdefault("transcripts", {})
    sessions = cursor.setdefault("sessions", {})
    state = dict(transcripts.get(str(path)) or {})
    session = sessions.get(session_id) or {"tool": tool, "started_at": None, "ended_at": None, "turns": 0, "tool_calls": 0, "files": [], "tasks": {}, "todos_hash": None}
    commit_times: list[datetime] = []
    lines = _read_new_lines(path, state)
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            parser(item, session, project_root, commit_times)
    _remember(transcripts, str(path), state)
    if not lines:
        return [], commit_times
    at = session["ended_at"] or core.now_iso()
    events = [{"kind": "session", "at": at, "tool": tool, "session": session_id, **{key: session[key] for key in ("started_at", "ended_at", "turns", "tool_calls", "files")}}]
    items = [{"text": task["text"], "status": task["status"]} for task in session["tasks"].values() if task["text"]][:MAX_TODO_ITEMS]
    digest = hashlib.sha256(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()
    if items and digest != session["todos_hash"]:
        events.append({"kind": "todos", "at": at, "tool": tool, "session": session_id, "items": items})
    session["todos_hash"] = digest
    _remember(sessions, session_id, session)
    return events, commit_times


def _commit_links(events: list[dict[str, Any]], commit_times: list[datetime]) -> list[str]:
    links: list[str] = []
    for event in events:
        at = _time(event.get("at")) if event["kind"] == "commit" else None
        if at and any(stamp.replace(microsecond=0) <= at <= stamp + COMMIT_LINK_WINDOW for stamp in commit_times):
            links.append(event["commit_full"])
    return links


def ingest(project_root: Path, tool: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append new Git, marker, and transcript facts. Callers hold the project lock."""
    project_root = project_root.resolve()
    stored, error = core.read_json(cursor_path(project_root))
    cursor = stored if error is None and isinstance(stored, dict) else {}
    before = json.dumps(cursor, sort_keys=True)
    events = load_events(project_root)
    known = {event["commit_full"] for event in events if event["kind"] == "commit" and isinstance(event.get("commit_full"), str)}
    new = _ingest_git(project_root, cursor, known) + _ingest_marker(project_root, cursor)
    links: list[str] = []
    if tool and isinstance(payload, dict):
        transcript_events, commit_times = _ingest_transcript(project_root, tool, payload, cursor)
        replaced = {event["session"] for event in transcript_events if event["kind"] == "session"}
        events = [event for event in events if not (event["kind"] == "session" and event.get("session") in replaced)]
        new += transcript_events
        if commit_times:
            links = _commit_links(events + new, commit_times)
    if new:
        _write_events(project_root, events + new)
    if json.dumps(cursor, sort_keys=True) != before:
        core.write_json(cursor_path(project_root), cursor)
    return {"added": len(new), "links": links}


def recent(project_root: Path, limit: int = 10) -> list[dict[str, Any]]:
    return sorted(load_events(project_root), key=_sort_key, reverse=True)[: max(1, min(limit, 50))]


def open_todos(project_root: Path, limit: int = MAX_TODO_ITEMS) -> list[dict[str, str]]:
    events = sorted(load_events(project_root), key=_sort_key)
    items: list[dict[str, str]] = []
    inspection = core.inspect_marker(project_root / core.MARKER_NAME)
    next_action = inspection["payload"].get("next_action") if inspection["state"] == "valid" else None
    if next_action and next_action != core.DEFAULT_NEXT:
        items.append({"source": "next_action", "text": mask(next_action), "status": "pending"})
    lists = [event for event in events if event["kind"] == "todos"]
    if lists:
        items.extend({"source": lists[-1]["tool"], "text": item["text"], "status": item["status"]} for item in lists[-1]["items"] if item.get("status") not in DONE_STATUSES)
    for index, event in enumerate(events):
        if event["kind"] != "todo":
            continue
        needle = event["text"].lower()[:40]
        later = (other.get("subject", "").lower() for other in events[index + 1 :] if other["kind"] == "commit")
        if not any(needle in subject for subject in later):
            items.append({"source": "commit", "text": event["text"], "status": "pending"})
    return items[:limit]


def summary(project_root: Path) -> dict[str, Any]:
    events = load_events(project_root)
    return {"open_todos": len(open_todos(project_root)), "last_event_at": max((event["at"] for event in events), key=lambda value: _time(value) or EPOCH, default=None)}


def snapshot(project_root: Path) -> dict[str, Any]:
    return {"summary": summary(project_root), "recent": recent(project_root, 30), "open_todos": open_todos(project_root)}


def format_event(event: dict[str, Any]) -> str:
    at = (_time(event.get("at")) or EPOCH).astimezone().strftime("%Y-%m-%d %H:%M")
    kind = event["kind"]
    if kind == "commit":
        detail = f"{event['commit']} {event['subject']} (+{event.get('insertions', 0)}/-{event.get('deletions', 0)}, {event.get('files_changed', 0)} files)"
    elif kind == "todo":
        detail = f"{event['commit']} {event['text']}"
    elif kind == "session":
        files = f" · {', '.join(event['files'])}" if event.get("files") else ""
        detail = f"{event['tool']} {event['session'][:8]} · {event['turns']} turns · {event['tool_calls']} tools{files}"
    elif kind == "todos":
        remaining = sum(1 for item in event["items"] if item.get("status") not in DONE_STATUSES)
        detail = f"{event['tool']} {event['session'][:8]} · {remaining}/{len(event['items'])} open"
    else:
        detail = event["text"]
    return f"{at} {kind:<11} {detail}"
