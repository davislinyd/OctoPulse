"""Project snapshots and report renderers for OctoPulse."""

from __future__ import annotations

import html
import json
import fcntl
import shlex
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import core


REPORT_DIR_NAME = ".octopulse-reports"
SNAPSHOT_FILE = "snapshot.json"
ACTIVITY_FILE = "activity.jsonl"
MAX_LEGACY_STATUS_BYTES = 65_536
MAX_ACTIVITY_EVENTS = 200
ACTIVITY_RETENTION_DAYS = 90
SNAPSHOT_STALE_DAYS = 7
TOOLS = {"codex", "claude", "antigravity", "grok"}
RESULTS = {"updated", "unchanged"}
LANGUAGES = {"zh-TW", "en"}

LABELS = {
    "zh-TW": {
        "project_report": "OctoPulse 專案報告",
        "portfolio_report": "OctoPulse 總報告",
        "overview": "總覽",
        "phase": "階段",
        "health": "健康度",
        "updated": "最後更新",
        "generated": "報告產生時間",
        "goal": "目前目標",
        "summary": "摘要",
        "next": "下一步",
        "verification": "驗證",
        "attention": "注意事項",
        "git": "Git 狀態",
        "history": "近期提交",
        "tools": "AI 工具活動",
        "signals": "風險訊號",
        "branch": "分支",
        "commit": "Commit",
        "dirty": "未提交變更",
        "upstream": "上游分支",
        "worktree": "工作樹檔案數",
        "legacy": "Legacy context",
        "yes": "是",
        "no": "否",
        "unknown": "未知",
        "none": "無",
        "projects": "專案",
        "portfolio_title": "專案進度。\n一眼掌握。",
        "project_title": "專案脈衝。\n清楚掌握。",
        "on_track": "進展順利",
        "needs_attention": "需要注意",
        "at_risk": "受阻風險",
        "on_hold": "暫停追蹤",
        "attention_required": "優先處理",
        "open_project": "查看專案",
        "back_overview": "返回總覽",
        "last_activity": "最後活動",
        "activity_30d": "近 30 天活動",
        "recent_activity": "近期活動",
        "git_facts": "Git 事實",
        "commits": "近期提交",
        "project_state": "專案狀態",
        "no_projects": "尚未有可顯示的專案。",
        "no_activity": "尚無活動資料",
        "handoff": "最新交接",
        "read_first": "優先讀取",
        "decisions": "決策",
        "where": "最近做到哪",
        "uncommitted": "還沒提交什麼",
        "completed": "最近完成了什麼",
        "clean": "工作區乾淨",
        "no_goal": "尚未寫入目標",
        "no_commits": "尚無提交",
        "files": "個檔案",
        "more_files": "還有 %s 個檔案",
        "just_now": "剛剛",
        "minutes_ago": " 分鐘前",
        "hours_ago": " 小時前",
        "days_ago": " 天前",
        "state_staged": "staged",
        "state_unstaged": "unstaged",
        "state_untracked": "untracked",
        "signal_dirty_worktree": "工作區有未提交變更",
        "signal_verification_not_run": "尚未記錄驗證",
        "signal_verification_failed": "最近一次驗證失敗",
        "signal_verification_partial": "驗證只完成一部分",
        "signal_attention_present": "有需要注意的事項",
        "signal_legacy_status_mismatch": "舊狀態檔與 marker 不一致",
        "signal_marker_not_valid": "進度標記還不能用",
        "signal_schema_migration_required": "進度標記仍是舊版",
        "signal_snapshot_stale": "報告快照已超過 14 天",
        "tool_claude": "Claude Code",
        "tool_codex": "ChatGPT Codex",
        "tool_grok": "Grok",
        "tool_unrecorded": "未記錄",
        "open_conversation": "打開對話",
    },
    "en": {
        "project_report": "OctoPulse Project Report",
        "portfolio_report": "OctoPulse Portfolio Report",
        "overview": "Overview",
        "phase": "Phase",
        "health": "Health",
        "updated": "Last updated",
        "generated": "Report generated",
        "goal": "Current goal",
        "summary": "Summary",
        "next": "Next action",
        "verification": "Verification",
        "attention": "Attention",
        "git": "Git status",
        "history": "Recent commits",
        "tools": "AI tool activity",
        "signals": "Risk signals",
        "branch": "Branch",
        "commit": "Commit",
        "dirty": "Uncommitted changes",
        "upstream": "Upstream",
        "worktree": "Working-tree file counts",
        "legacy": "Legacy context",
        "yes": "Yes",
        "no": "No",
        "unknown": "Unknown",
        "none": "None",
        "projects": "Projects",
        "portfolio_title": "Project progress.\nAt a glance.",
        "project_title": "Project pulse.\nIn focus.",
        "on_track": "On track",
        "needs_attention": "Needs attention",
        "at_risk": "At risk",
        "on_hold": "On hold",
        "attention_required": "Needs attention",
        "open_project": "Open project",
        "back_overview": "Back to overview",
        "last_activity": "Last activity",
        "activity_30d": "Activity (30 days)",
        "recent_activity": "Recent activity",
        "git_facts": "Git facts",
        "commits": "Recent commits",
        "project_state": "Project state",
        "no_projects": "No projects to display yet.",
        "no_activity": "No activity recorded",
        "handoff": "Latest handoff",
        "read_first": "Read first",
        "decisions": "Decisions",
        "where": "Latest progress",
        "uncommitted": "Not committed yet",
        "completed": "Recently completed",
        "clean": "Clean worktree",
        "no_goal": "No goal recorded",
        "no_commits": "No commits yet",
        "files": "files",
        "more_files": "%s more files",
        "just_now": "just now",
        "minutes_ago": " minutes ago",
        "hours_ago": " hours ago",
        "days_ago": " days ago",
        "state_staged": "staged",
        "state_unstaged": "unstaged",
        "state_untracked": "untracked",
        "signal_dirty_worktree": "Uncommitted changes",
        "signal_verification_not_run": "Verification has not been recorded",
        "signal_verification_failed": "The latest verification failed",
        "signal_verification_partial": "Verification is only partial",
        "signal_attention_present": "Attention items are recorded",
        "signal_legacy_status_mismatch": "Legacy status does not match the marker",
        "signal_marker_not_valid": "The progress marker is not usable",
        "signal_schema_migration_required": "The progress marker is still an older schema",
        "signal_snapshot_stale": "The report snapshot is older than 14 days",
        "tool_claude": "Claude Code",
        "tool_codex": "ChatGPT Codex",
        "tool_grok": "Grok",
        "tool_unrecorded": "Not recorded",
        "open_conversation": "Open conversation",
    },
}


def labels(language: str) -> dict[str, str]:
    return LABELS[language if language in LANGUAGES else "zh-TW"]


def report_dir(project_root: Path) -> Path:
    return project_root / REPORT_DIR_NAME


def snapshot_path(project_root: Path) -> Path:
    return report_dir(project_root) / SNAPSHOT_FILE


def activity_path(project_root: Path) -> Path:
    return report_dir(project_root) / ACTIVITY_FILE


@contextmanager
def report_lock(path: Path):
    """Acquire a non-blocking POSIX lock for a hook report refresh."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def project_hook_lock(project_root: Path):
    return report_lock(report_dir(project_root) / ".hook.lock")


def portfolio_hook_lock():
    return report_lock(core.octopulse_home() / "locks" / "portfolio.hook.lock")


SESSION_TOOLS = {"claude", "codex", "grok"}
SESSION_FILE = Path(".ai") / "octopulse-sessions.jsonl"
MAX_SESSION_RECORDS = 200
RESUME_COMMANDS = {
    "claude": ("claude", "--resume"),
    "codex": ("codex", "resume"),
    "grok": ("grok", "--resume"),
}


def session_path(project_root: Path) -> Path:
    return project_root / SESSION_FILE


def ensure_session_exclude(project_root: Path) -> None:
    raw_path, error = core.run_git(project_root, ["rev-parse", "--git-path", "info/exclude"])
    if error or not raw_path:
        return
    exclude = Path(raw_path)
    if not exclude.is_absolute():
        exclude = project_root / exclude
    entry = f"/{SESSION_FILE.as_posix()}"
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if entry not in existing.splitlines():
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(existing.rstrip() + ("\n" if existing.strip() else "") + entry + "\n", encoding="utf-8")


def load_sessions(project_root: Path) -> dict[str, dict[str, str]]:
    path = session_path(project_root)
    sessions: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return sessions
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        commit = item.get("commit")
        tool = item.get("tool")
        if not isinstance(commit, str) or tool not in SESSION_TOOLS:
            continue
        record = {"commit": commit, "tool": tool, "at": item.get("at") if isinstance(item.get("at"), str) else ""}
        session = item.get("session")
        if isinstance(session, str) and session.strip():
            record["session"] = session.strip()
        sessions[commit] = record
    return sessions


def record_session(project_root: Path, commit: str, tool: str, session: str | None = None) -> dict[str, str]:
    if tool not in SESSION_TOOLS:
        raise ValueError("session tool must be claude, codex, or grok")
    full, error = core.run_git(project_root, ["rev-parse", "--verify", f"{commit}^{{commit}}"])
    if error or not full:
        raise ValueError(f"commit not found: {commit}")
    cleaned = session.strip() if isinstance(session, str) else ""
    if cleaned and (len(cleaned) > 200 or any(character.isspace() for character in cleaned)):
        raise ValueError("session id must be a single token")
    entry = {"commit": full, "tool": tool, "at": core.now_iso()}
    if cleaned:
        entry["session"] = cleaned
    path = session_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    existing.append(json.dumps(entry, ensure_ascii=False))
    path.write_text("".join(f"{line}\n" for line in existing[-MAX_SESSION_RECORDS:]), encoding="utf-8")
    ensure_session_exclude(project_root)
    return entry


def resume_argv(project_root: Path, commit: str) -> list[str]:
    full, error = core.run_git(project_root, ["rev-parse", "--verify", f"{commit}^{{commit}}"])
    if error or not full:
        raise ValueError(f"commit not found: {commit}")
    record = load_sessions(project_root).get(full)
    if record is None:
        raise ValueError(f"no local session record for {full}")
    session = record.get("session")
    if not session:
        raise ValueError(f"commit {full} has no session id")
    command = RESUME_COMMANDS.get(record["tool"])
    if command is None:
        raise ValueError(f"unknown session tool: {record['tool']}")
    return [*command, session]


def find_session_root(commit: str, directory: Path | None = None) -> tuple[Path, str]:
    roots: list[Path] = []
    start = core.git_root(directory or Path.cwd())
    if start is not None:
        roots.append(start)
    for raw in core.load_config()["roots"]:
        path = Path(raw)
        if path not in roots:
            roots.append(path)
    found: list[tuple[Path, str]] = []
    for root in roots:
        if core.git_root(root) != root.resolve():
            continue
        full, error = core.run_git(root, ["rev-parse", "--verify", f"{commit}^{{commit}}"])
        if error or not full:
            continue
        found.append((root.resolve(), full))
    if not found:
        raise ValueError(f"commit not found: {commit}")
    for root, full in found:
        if full in load_sessions(root):
            return root, full
    return found[0]


def install_resume_handler(applications: Path, octopulse_bin: str) -> Path:
    app = applications / "OctoPulse Resume.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    (app / "Contents" / "Info.plist").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>io.octopulse.resume</string>
<key>CFBundleName</key><string>OctoPulse Resume</string>
<key>CFBundleExecutable</key><string>octopulse-resume</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleURLTypes</key><array><dict>
<key>CFBundleURLName</key><string>OctoPulse Resume</string>
<key>CFBundleURLSchemes</key><array><string>octopulse</string></array>
</dict></array>
</dict></plist>
""",
        encoding="utf-8",
    )
    script = macos / "octopulse-resume"
    script.write_text(
        "#!/bin/sh\n"
        "url=\"$1\"\n"
        "commit=$(printf '%s' \"$url\" | sed -n 's/.*commit=\\([^&]*\\).*/\\1/p')\n"
        f"exec {shlex.quote(octopulse_bin)} resume --commit \"$commit\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return app


def annotate_history(project_root: Path, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sessions = load_sessions(project_root)
    for entry in history:
        record = sessions.get(entry.get("commit_full"))
        if record is None:
            continue
        entry["tool"] = record["tool"]
        if record.get("session"):
            entry["session"] = record["session"]
    return history


def ensure_local_exclude(project_root: Path) -> None:
    raw_path, error = core.run_git(project_root, ["rev-parse", "--git-path", "info/exclude"])
    if error or not raw_path:
        return
    exclude = Path(raw_path)
    if not exclude.is_absolute():
        exclude = project_root / exclude
    entry = f"/{REPORT_DIR_NAME}/"
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if entry not in existing.splitlines():
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(existing.rstrip() + ("\n" if existing.strip() else "") + entry + "\n", encoding="utf-8")


def _git(project_root: Path, args: list[str]) -> str:
    value, error = core.run_git(project_root, args)
    return value if error is None and value is not None else ""


def _worktree(project_root: Path) -> dict[str, Any]:
    porcelain = _git(project_root, ["status", "--porcelain=v1"])
    counts = {"staged": 0, "unstaged": 0, "untracked": 0}
    files: list[dict[str, str]] = []
    visible_count = 0
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        if line.startswith("??"):
            counts["untracked"] += 1
            state = "untracked"
        else:
            if line[0] != " ":
                counts["staged"] += 1
            if line[1] != " ":
                counts["unstaged"] += 1
            state = "unstaged" if line[1] != " " else "staged"
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        visible = path.rstrip("/")
        if visible in {".octopulse", ".octopulse-reports", ".ai/octopulse-sessions.jsonl"} or visible.startswith(".octopulse-reports/"):
            continue
        visible_count += 1
        if len(files) < 12:
            files.append({"path": path[:240], "state": state})
    return {**counts, "files": files, "omitted": max(0, visible_count - len(files))}


def _history(project_root: Path, count: int) -> list[dict[str, Any]]:
    count = max(1, min(count, 50))
    output = _git(project_root, ["log", f"--max-count={count}", "--date=iso-strict", "--name-only", "--pretty=format:%h%x1f%H%x1f%ad%x1f%s"])
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in output.splitlines():
        if "\x1f" in line:
            if current:
                entries.append(current)
            commit, commit_full, committed_at, subject = line.split("\x1f", 3)
            current = {"commit": commit, "commit_full": commit_full, "committed_at": committed_at, "subject": subject[:240], "files_changed": 0, "files": []}
            continue
        path = line.strip()
        if current and path:
            current["files_changed"] += 1
            if len(current["files"]) < 8:
                current["files"].append(path[:240])
    if current:
        entries.append(current)
    return entries


def _legacy_status(project_root: Path, mode: str) -> dict[str, Any] | None:
    if mode == "never":
        return None
    path = project_root / ".ai" / "status.json"
    if not path.is_file() or path.stat().st_size > MAX_LEGACY_STATUS_BYTES:
        return None
    payload, error = core.read_json(path)
    if error or not isinstance(payload, dict):
        return None
    verification = payload.get("verification") if isinstance(payload.get("verification"), dict) else {}
    selected = {
        "phase": payload.get("phase"),
        "health": payload.get("health"),
        "goal": payload.get("current_goal"),
        "summary": payload.get("latest_summary"),
        "next_action": payload.get("next_action"),
        "last_updated": payload.get("last_updated"),
        "verification_status": verification.get("status"),
    }
    return {key: value for key, value in selected.items() if isinstance(value, str)}


def _parse_activity(project_root: Path) -> list[dict[str, str]]:
    path = activity_path(project_root)
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-MAX_ACTIVITY_EVENTS:]
    except OSError:
        return []
    events: list[dict[str, str]] = []
    cutoff = datetime.now().astimezone() - timedelta(days=ACTIVITY_RETENTION_DAYS)
    for line in lines:
        if len(line.encode("utf-8")) > 1024:
            continue
        try:
            item = json.loads(line)
            timestamp = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if timestamp < cutoff or item.get("tool") not in TOOLS or item.get("event") not in {"start", "finish"}:
            continue
        result = item.get("result") or None
        if result is not None and result not in RESULTS:
            continue
        events.append({"timestamp": timestamp.isoformat(timespec="seconds"), "tool": item["tool"], "event": item["event"], "result": result or ""})
    return events


def record_activity(project_root: Path, tool: str, event: str, result: str | None = None) -> dict[str, str]:
    if tool not in TOOLS or event not in {"start", "finish"} or (result is not None and result not in RESULTS):
        raise ValueError("invalid activity event")
    ensure_local_exclude(project_root)
    report_dir(project_root).mkdir(parents=True, exist_ok=True)
    entry = {"timestamp": core.now_iso(), "tool": tool, "event": event}
    if result:
        entry["result"] = result
    events = _parse_activity(project_root) + [entry]
    activity_path(project_root).write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in events[-MAX_ACTIVITY_EVENTS:]), encoding="utf-8")
    return entry


def _activity_summary(events: list[dict[str, str]]) -> dict[str, Any]:
    if not events:
        return {"state": "unknown", "tools": [], "recent_events": []}
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        item = grouped.setdefault(event["tool"], {"tool": event["tool"], "sessions": 0, "last_used_at": event["timestamp"], "last_result": ""})
        item["last_used_at"] = max(item["last_used_at"], event["timestamp"])
        if event["event"] == "finish":
            item["sessions"] += 1
            item["last_result"] = event["result"]
    return {"state": "recorded", "tools": sorted(grouped.values(), key=lambda item: item["tool"]), "recent_events": events[-MAX_ACTIVITY_EVENTS:]}


def _signals(status: dict[str, Any] | None, git: dict[str, Any], legacy: dict[str, Any] | None) -> list[str]:
    signals: list[str] = []
    if git.get("dirty"):
        signals.append("dirty_worktree")
    if status:
        verification = status["verification"]
        if verification["status"] in {"failed", "not_run", "partial"}:
            signals.append(f"verification_{verification['status']}")
        if status["attention"]:
            signals.append("attention_present")
        if legacy and any(legacy.get(field) and legacy[field] != status.get(field) for field in ("phase", "health")):
            signals.append("legacy_status_mismatch")
    else:
        signals.append("marker_not_valid")
    return signals


def collect_project_snapshot(project_root: Path, history: int = 20, legacy_status: str = "auto") -> dict[str, Any]:
    project_root = project_root.resolve()
    inspection = core.inspect_marker(project_root / core.MARKER_NAME)
    status = inspection.get("payload") if inspection["state"] in {"valid", "migration_required"} else None
    git = core.git_facts(project_root)
    git["upstream"] = _git(project_root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]) or None
    git["worktree"] = _worktree(project_root)
    legacy = _legacy_status(project_root, legacy_status)
    events = _parse_activity(project_root)
    snapshot = {
        "schema_version": 1,
        "generated_at": core.now_iso(),
        "project": {"name": status["name"] if status else project_root.name, "path": str(project_root)},
        "marker": {"state": inspection["state"], "errors": inspection["errors"], "status": status},
        "git": git,
        "history": annotate_history(project_root, _history(project_root, history)),
        "legacy_context": legacy,
        "activity": _activity_summary(events),
    }
    snapshot["signals"] = _signals(status, git, legacy)
    if inspection["state"] == "migration_required":
        snapshot["signals"].append("schema_migration_required")
    snapshot["source_signature"] = core.fingerprint([{key: value for key, value in snapshot.items() if key not in {"generated_at", "source_signature"}}])
    return snapshot


def _read_snapshot(project_root: Path) -> dict[str, Any] | None:
    payload, error = core.read_json(snapshot_path(project_root))
    return payload if error is None and isinstance(payload, dict) else None


def eligible_hook_project(directory: Path) -> Path | None:
    root = core.git_root(directory)
    if root is None:
        return None
    context = core.context_for(root)
    if context["state"] != "valid" or not context["registered"]:
        return None
    inspection = core.inspect_marker(root / core.MARKER_NAME)
    status = inspection.get("payload")
    if not status or status["phase"] == "paused" or status["health"] == "stale":
        return None
    return root


def _value(value: Any) -> str:
    return str(value) if value not in {None, ""} else "—"


def _visible_field(value: str | None, placeholder: str) -> str:
    return value if value and value != placeholder else ""


def _signal_text(signal: str, language: str) -> str:
    return labels(language).get(f"signal_{signal}", signal)


def project_markdown(snapshot: dict[str, Any], language: str) -> str:
    t = labels(language)
    status = snapshot["marker"].get("status")
    git = snapshot["git"]
    history = snapshot.get("history") or []
    latest = history[0] if history else None
    lines = [
        f"# {t['project_report']}: {snapshot['project']['name']}",
        "",
        f"## {t['where']}",
        "",
        f"- {latest['subject'] if latest else t['no_commits']}",
        f"- {t['branch']}: {_value(git.get('branch'))} · {t['commit']}: {_value(git.get('commit'))} · {t['updated']}: {_value(latest['committed_at'] if latest else None)}",
        "",
        f"## {t['uncommitted']}",
        "",
    ]
    worktree = git.get("worktree") or {}
    files = worktree.get("files") or []
    if files:
        lines.extend(f"- {item['state']}: {item['path']}" for item in files)
        omitted = worktree.get("omitted") or 0
        if omitted:
            lines.append(f"- {t['more_files'].replace('%s', str(omitted))}")
    else:
        lines.append(f"- {t['clean']}")
    lines.extend(["", f"## {t['completed']}", ""])
    current_day = ""
    for item in history:
        day = str(item["committed_at"])[:10]
        if day != current_day:
            lines.extend(["", f"### {day}", ""])
            current_day = day
        shown = ", ".join(item.get("files") or [])
        extra = item.get("files_changed", 0) - len(item.get("files") or [])
        detail = f"{item.get('files_changed', 0)} {t['files']}"
        if shown:
            detail = f"{detail}: {shown}"
        if extra > 0:
            detail = f"{detail} (+{extra})"
        tool = t.get(f"tool_{item.get('tool')}", t["tool_unrecorded"])
        lines.append(f"- `{item['commit']}` {item['committed_at']}: {item['subject']} ({detail}) · {tool}")
    if not history:
        lines.append(f"- {t['none']}")
    lines.extend(["", f"## {t['project_state']}", ""])
    if status:
        goal = _visible_field(status.get("goal"), core.DEFAULT_GOAL)
        summary = _visible_field(status.get("summary"), core.DEFAULT_GOAL)
        next_action = _visible_field(status.get("next_action"), core.DEFAULT_NEXT)
        if not any((goal, summary, next_action)):
            lines.append(f"- {t['no_goal']}")
        else:
            if goal:
                lines.append(f"- {t['goal']}: {goal}")
            if summary and summary != goal:
                lines.append(f"- {t['summary']}: {summary}")
            if next_action:
                lines.append(f"- {t['next']}: {next_action}")
        lines.append(f"- {t['verification']}: {status['verification']['status']} ({_value(status['verification']['last_command'])})")
        lines.append(f"- {t['attention']}: {', '.join(status['attention']) or t['none']}")
        handoff = status.get("handoff")
        if handoff:
            lines.extend(["", f"## {t['handoff']}", "", f"- {t['tools']}: {handoff['tool']} · {handoff['created_at']}", f"- {t['commit']}: {_value(handoff['commit'])}", f"- {t['read_first']}: {', '.join(handoff['read_first']) or t['none']}", f"- {t['decisions']}: {'; '.join(handoff['decisions']) or t['none']}"])
    else:
        lines.append(f"- {snapshot['marker']['state']}")
    signal_lines = [f"- {_signal_text(signal, language)}" for signal in snapshot["signals"]] or [f"- {t['none']}"]
    lines.extend(["", f"## {t['signals']}", "", *signal_lines, "", f"## {t['tools']}", ""])
    tools = snapshot["activity"]["tools"]
    lines.extend([f"- {item['tool']}: {item['sessions']} sessions, {item['last_used_at']}, {item['last_result'] or t['unknown']}" for item in tools] or [f"- {t['no_activity']}"])
    if snapshot["legacy_context"]:
        lines.extend(["", f"## {t['legacy']}", "", f"- {json.dumps(snapshot['legacy_context'], ensure_ascii=False)}"])
    return "\n".join(lines).rstrip() + "\n"


def _console_html(payload_data: dict[str, Any], language: str, single_project: bool) -> str:
    payload = json.dumps(payload_data, ensure_ascii=False).replace("</", "<\\/")
    translations = json.dumps(LABELS, ensure_ascii=False).replace("</", "<\\/")
    return """<!doctype html>
<html lang="__LANG__">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OctoPulse</title>
<style>
:root{color-scheme:light;--ink:#1d1d1f;--muted:#6e6e73;--line:#d2d2d7;--surface:#f5f5f7;--blue:#0071e3;--green:#1a9b5c;--amber:#e59600;--red:#d92d20;--gray:#a1a1a6;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif}*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font-size:15px;line-height:1.45}.topbar{position:sticky;top:0;z-index:5;height:52px;display:flex;align-items:center;gap:28px;padding:0 max(24px,calc((100vw - 1240px)/2));background:rgba(255,255,255,.82);backdrop-filter:saturate(180%) blur(18px);border-bottom:1px solid rgba(0,0,0,.08)}.brand{font-size:20px;font-weight:650;letter-spacing:-.04em}.topbar button{min-height:36px;border:0;background:transparent;color:var(--muted);font:inherit;cursor:pointer}.topbar button:hover,.topbar button[aria-pressed="true"]{color:var(--blue)}.topbar button:focus-visible,.project-row:focus-visible,.attention:focus-visible{outline:3px solid rgba(0,113,227,.45);outline-offset:3px}.tools{margin-left:auto;display:flex;align-items:center;gap:4px}.updated{font-size:12px;color:var(--muted);white-space:nowrap}main{max-width:1240px;margin:0 auto;padding:64px 32px 88px}.hero{max-width:760px;margin-bottom:38px}.hero h1{margin:0;white-space:pre-line;font-size:clamp(44px,7vw,76px);letter-spacing:-.065em;line-height:.98;font-weight:650}.hero p{margin:22px 0 0;color:var(--muted);font-size:19px;max-width:610px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);margin:0 0 28px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.metric{min-height:112px;padding:24px 20px;border-right:1px solid var(--line)}.metric:last-child{border-right:0}.metric-value{display:flex;align-items:center;gap:10px;font-size:34px;line-height:1;font-weight:650;letter-spacing:-.04em}.metric-label{margin-top:10px;color:var(--muted);font-size:13px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;flex:0 0 auto}.active,.stable{background:var(--green)}.needs_attention{background:var(--amber)}.blocked{background:var(--red)}.stale,.unknown{background:var(--gray)}.attention{width:100%;display:grid;grid-template-columns:148px 1fr 1.35fr auto;gap:20px;align-items:center;padding:20px 24px;margin:0 0 34px;border:1px solid var(--line);border-left:5px solid var(--amber);border-radius:18px;background:#fff;text-align:left;font:inherit;cursor:pointer}.attention:hover{border-color:#aaa}.eyebrow{font-size:12px;color:var(--muted);margin-bottom:3px}.attention strong{font-size:17px}.attention-action{color:var(--blue);white-space:nowrap;font-weight:600}.section-head{display:flex;align-items:end;justify-content:space-between;margin:0 0 12px}.section-head h2{margin:0;font-size:24px;letter-spacing:-.03em}.section-head span{color:var(--muted);font-size:13px}.projects{border-top:1px solid var(--line)}.project-row{width:100%;display:grid;grid-template-columns:minmax(250px,2fr) minmax(100px,.75fr) minmax(150px,1fr) minmax(130px,.85fr) 116px 32px;gap:16px;align-items:center;padding:20px 8px;border:0;border-bottom:1px solid var(--line);background:#fff;text-align:left;font:inherit;color:inherit;cursor:pointer}.project-row:hover,.project-row[aria-current="true"]{background:#f5f9ff}.project-name{display:flex;align-items:flex-start;gap:12px}.project-name strong{display:block;font-size:17px;letter-spacing:-.02em}.project-name span{display:block;max-width:370px;margin-top:3px;color:var(--muted);font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.cell-label{display:block;margin-bottom:3px;color:var(--muted);font-size:12px}.cell-value{display:block;font-size:13px}.verify{display:flex;gap:7px;align-items:center}.verify.passed{color:var(--green)}.verify.failed{color:var(--red)}.verify.not_run,.verify.partial{color:var(--amber)}.cadence{height:28px;display:flex;align-items:end;gap:2px}.cadence i{width:3px;min-height:2px;background:var(--blue);border-radius:3px 3px 0 0}.cadence.empty{align-items:center;color:var(--gray);font-size:18px}.chevron{color:var(--blue);font-size:25px;font-weight:300}.detail{margin-top:38px;padding:30px;border:1px solid var(--line);border-radius:24px;background:#fff;box-shadow:0 14px 40px rgba(0,0,0,.06)}.detail-top{display:flex;justify-content:space-between;gap:16px;align-items:start;margin-bottom:28px}.detail-top h1{margin:0;font-size:38px;letter-spacing:-.045em}.detail-path{margin:6px 0 0;color:var(--muted);font-size:13px;overflow-wrap:anywhere}.back{border:0;background:transparent;color:var(--blue);font:inherit;font-weight:600;cursor:pointer;min-height:36px}.detail-grid{display:grid;grid-template-columns:1.3fr 1fr 1fr;gap:28px}.detail-section{min-width:0}.detail-section+ .detail-section{border-left:1px solid var(--line);padding-left:28px}.detail-section h2{margin:0 0 14px;font-size:17px;letter-spacing:-.02em}.fact{padding:11px 0;border-top:1px solid #e8e8ed}.fact:first-of-type{border-top:0;padding-top:0}.fact-label{display:block;color:var(--muted);font-size:12px}.fact-value{display:block;margin-top:3px;white-space:pre-line;overflow-wrap:anywhere}.risk-list,.commit-list,.tool-list{margin:0;padding:0;list-style:none}.risk-list li,.tool-list li{padding:8px 0;border-top:1px solid #e8e8ed}.risk-list li:first-child,.tool-list li:first-child{border-top:0}.commit-list li{padding:9px 0;border-top:1px solid #e8e8ed}.commit-list code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--blue)}.commit-time{display:block;color:var(--muted);font-size:12px;margin-top:2px}.empty{padding:28px 0;color:var(--muted)}.lead{margin:8px 0 0;font-size:28px;letter-spacing:-.03em;line-height:1.25}.meta{margin:8px 0 0;color:var(--muted)}.review{margin:0 0 28px}.day{margin:18px 0 8px;color:var(--muted);font-size:13px}.file-list{margin:0;padding:0;list-style:none}.file-list li{padding:8px 0;border-top:1px solid #e8e8ed}.state{display:inline-block;min-width:78px;margin-right:8px;color:var(--muted);font-size:12px}@media(max-width:760px){.topbar{gap:12px;padding:0 16px}.brand{font-size:18px}.updated{display:none}main{padding:42px 18px 60px}.hero h1{font-size:48px}.hero p{font-size:17px}.metrics{grid-template-columns:1fr 1fr}.metric:nth-child(2){border-right:0}.metric:nth-child(-n+2){border-bottom:1px solid var(--line)}.metric{min-height:96px;padding:18px 12px}.attention{grid-template-columns:1fr;gap:10px;padding:18px}.attention-action{padding-top:4px}.project-row{grid-template-columns:1fr 34px;gap:12px;padding:18px 4px}.project-row .phase,.project-row .verification,.project-row .activity,.project-row .cadence-wrap{display:none}.detail{margin-top:28px;padding:22px 18px;border-radius:20px}.detail-top h1{font-size:32px}.detail-grid{grid-template-columns:1fr;gap:24px}.detail-section+.detail-section{border-left:0;border-top:1px solid var(--line);padding:24px 0 0}.tools button{font-size:13px}.topbar .overview-label{display:none}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style>
<body>
<header class="topbar"><div class="brand">OctoPulse</div><button id="overview" type="button" aria-pressed="true">Overview</button><div class="tools"><button id="zh" type="button">繁中</button><button id="en" type="button">EN</button><span class="updated" id="updated"></span></div></header>
<main id="app"></main>
<script>
const data=__PAYLOAD__,labels=__LABELS__,singleProject=__SINGLE__,defaultLang="__LANG__";
let lang=new URLSearchParams(location.search).get("lang")==="en"?"en":defaultLang;
const t=()=>labels[lang]||labels["zh-TW"],escapeHtml=value=>{const node=document.createElement("span");node.textContent=value??"—";return node.innerHTML},projectKey=project=>project.project.path,projectStatus=project=>project.marker?.status||null,projectHealth=project=>projectStatus(project)?.health||project.state||project.marker?.state||"unknown";
function stateProject(){return new URLSearchParams(location.hash.slice(1)).get("project")}function writeState(key,replace=false){const url=new URL(location);url.searchParams.set("lang",lang);url.hash=key?"project="+encodeURIComponent(key):"";history[replace?"replaceState":"pushState"](null,"",url);render()}
function cadence(project){const events=project.activity?.recent_events||[];if(!events.length)return '<span class="cadence empty" aria-label="'+escapeHtml(t().no_activity)+'">—</span>';const now=Date.now(),day=86400000,buckets=Array(30).fill(0);events.forEach(event=>{const age=Math.floor((now-new Date(event.timestamp).getTime())/day);if(age>=0&&age<30)buckets[29-age]++});if(!buckets.some(Boolean))return '<span class="cadence empty" aria-label="'+escapeHtml(t().no_activity)+'">—</span>';const max=Math.max(...buckets);return '<span class="cadence" aria-label="'+escapeHtml(t().activity_30d)+'">'+buckets.map(value=>'<i style="height:'+Math.max(2,Math.round(value/max*26))+'px"></i>').join('')+'</span>'}
function healthDot(health){return '<i class="dot '+escapeHtml(health)+'"></i>'}function verify(status){const value=status?.verification?.status||"unknown";return '<span class="verify '+escapeHtml(value)+'"><span>'+({passed:"✓",failed:"×",not_run:"•",partial:"•"}[value]||"—")+'</span>'+escapeHtml(value)+'</span>'}function handoff(status){const h=status?.handoff;if(!h)return '';return '<h2>'+escapeHtml(t().handoff)+'</h2><div class="fact"><span class="fact-label">'+escapeHtml(t().tools)+'</span><span class="fact-value">'+escapeHtml(h.tool+' · '+h.created_at)+'</span></div><div class="fact"><span class="fact-label">'+escapeHtml(t().read_first)+'</span><span class="fact-value">'+escapeHtml(h.read_first.join(', ')||t().none)+'</span></div><div class="fact"><span class="fact-label">'+escapeHtml(t().decisions)+'</span><span class="fact-value">'+escapeHtml(h.decisions.join('\\n')||t().none)+'</span></div>'}function firstTool(project){const tool=project.activity?.tools?.slice().sort((a,b)=>String(b.last_used_at).localeCompare(String(a.last_used_at)))[0];return tool?tool.tool+" · "+tool.last_used_at:t().no_activity}
function counts(){const result={on_track:0,needs_attention:0,at_risk:0,on_hold:0};data.projects.forEach(project=>{const status=projectStatus(project),health=projectHealth(project);if(health==="blocked")result.at_risk++;else if(health==="needs_attention")result.needs_attention++;else if(health==="stale"||status?.phase==="paused")result.on_hold++;else result.on_track++});return result}
function attentionProject(){return data.projects.find(project=>{const status=projectStatus(project);return status&&(projectHealth(project)==="blocked"||projectHealth(project)==="needs_attention"||(project.signals||[]).length)})}
function renderMetrics(){const c=counts(),items=[["on_track","active"],["needs_attention","needs_attention"],["at_risk","blocked"],["on_hold","stale"]];return '<section class="metrics">'+items.map(([key,health])=>'<div class="metric"><div class="metric-value">'+healthDot(health)+c[key]+'</div><div class="metric-label">'+escapeHtml(t()[key])+'</div></div>').join('')+'</section>'}
function renderAttention(project){if(!project)return '';const status=projectStatus(project),signal=(project.signals||[])[0]||projectHealth(project);return '<button class="attention" type="button" data-project="'+escapeHtml(projectKey(project))+'"><div><div class="eyebrow">'+escapeHtml(t().attention_required)+'</div><strong>'+escapeHtml(project.project.name)+'</strong></div><div><div class="eyebrow">'+escapeHtml(t().signals)+'</div><span>'+escapeHtml(signal)+'</span></div><div><div class="eyebrow">'+escapeHtml(t().next)+'</div><span>'+escapeHtml(status?.next_action||"—")+'</span></div><span class="attention-action">'+escapeHtml(t().open_project)+' ›</span></button>'}
const PLACEHOLDER_GOAL="Keep this project visible in OctoPulse.",PLACEHOLDER_NEXT="Review the OctoPulse report.";
function fieldValue(status,key){const value=(status&&status[key])||"";if((key==="goal"||key==="summary")&&value===PLACEHOLDER_GOAL)return "";if(key==="next_action"&&value===PLACEHOLDER_NEXT)return "";return value}
function signalText(signal){return t()["signal_"+signal]||signal}
function relativeTime(iso){if(!iso)return "—";const then=new Date(iso).getTime();if(Number.isNaN(then))return iso;const minutes=Math.round((Date.now()-then)/60000);if(minutes<1)return t().just_now;if(minutes<60)return minutes+t().minutes_ago;const hours=Math.round(minutes/60);if(hours<24)return hours+t().hours_ago;const days=Math.round(hours/24);if(days<14)return days+t().days_ago;return String(iso).slice(0,16).replace("T"," ")}
function latestCommit(project){return (project.history||[])[0]||null}
function lead(project){const commit=latestCommit(project),git=project.git||{};return '<section class="review"><p class="eyebrow">'+escapeHtml(t().where)+'</p><h2 class="lead">'+escapeHtml(commit?commit.subject:t().no_commits)+'</h2><p class="meta">'+escapeHtml([git.branch||"—",git.commit||"—",commit?relativeTime(commit.committed_at):"—"].join(" · "))+'</p></section>'}
function uncommitted(project){const worktree=(project.git&&project.git.worktree)||{},files=worktree.files||[];if(!files.length)return '<p class="empty">'+escapeHtml(t().clean)+'</p>';const omitted=worktree.omitted||0;return '<ul class="file-list">'+files.map(file=>'<li><span class="state">'+escapeHtml(t()["state_"+file.state]||file.state)+'</span>'+escapeHtml(file.path)+'</li>').join('')+(omitted?'<li>'+escapeHtml(String(t().more_files).replace("%s",String(omitted)))+'</li>':'')+'</ul>'}
function toolLabel(commit){return commit.tool?(t()["tool_"+commit.tool]||commit.tool):t().tool_unrecorded}function resumeLink(commit){if(!commit.session||!commit.commit_full)return "";return ' <a href="octopulse://resume?commit='+encodeURIComponent(commit.commit_full)+'">'+escapeHtml(t().open_conversation)+'</a>'}function timeline(commits){if(!commits.length)return '<p class="empty">'+escapeHtml(t().none)+'</p>';let html="",day="";commits.forEach(commit=>{const next=String(commit.committed_at||"").slice(0,10);if(next!==day){html+='<h3 class="day">'+escapeHtml(next)+'</h3>';day=next}const names=(commit.files||[]).join(", ");const extra=(commit.files_changed||0)-(commit.files||[]).length;html+='<div class="fact"><span class="fact-label">'+escapeHtml(commit.commit+" · "+relativeTime(commit.committed_at)+" · "+toolLabel(commit))+'</span><span class="fact-value">'+escapeHtml(commit.subject)+resumeLink(commit)+'</span><span class="commit-time">'+escapeHtml(String(commit.files_changed||0)+" "+t().files+(names?" · "+names:"")+(extra>0?" · +"+extra:""))+'</span></div>'});return html}
function written(status){if(!status)return '<p class="empty">'+escapeHtml(t().no_goal)+'</p>';const goal=fieldValue(status,"goal"),summary=fieldValue(status,"summary"),next=fieldValue(status,"next_action");let html="";if(!goal&&!(summary&&summary!==goal)&&!next)html+='<p class="empty">'+escapeHtml(t().no_goal)+'</p>';if(goal)html+='<div class="fact"><span class="fact-label">'+escapeHtml(t().goal)+'</span><span class="fact-value">'+escapeHtml(goal)+'</span></div>';if(summary&&summary!==goal)html+='<div class="fact"><span class="fact-label">'+escapeHtml(t().summary)+'</span><span class="fact-value">'+escapeHtml(summary)+'</span></div>';if(next)html+='<div class="fact"><span class="fact-label">'+escapeHtml(t().next)+'</span><span class="fact-value">'+escapeHtml(next)+'</span></div>';html+='<div class="fact"><span class="fact-label">'+escapeHtml(t().verification)+'</span><span class="fact-value">'+verify(status)+'<br>'+escapeHtml((status.verification&&status.verification.last_command)||"—")+'</span></div>';if((status.attention||[]).length)html+='<div class="fact"><span class="fact-label">'+escapeHtml(t().attention)+'</span><span class="fact-value">'+escapeHtml(status.attention.join(", "))+'</span></div>';return html||'<p class="empty">'+escapeHtml(t().no_goal)+'</p>'}
function renderRow(project){const status=projectStatus(project),health=projectHealth(project),commit=latestCommit(project),next=status?fieldValue(status,"next_action"):"",dirty=Boolean(project.git&&project.git.dirty);if(!status&&!commit)return '<button class="project-row" type="button" data-project="'+escapeHtml(projectKey(project))+'"><div class="project-name">'+healthDot(health)+'<div><strong>'+escapeHtml(project.project.name)+'</strong><span>'+escapeHtml(project.state||project.marker?.state||t().unknown)+'</span></div></div><span class="chevron">›</span></button>';return '<button class="project-row" type="button" data-project="'+escapeHtml(projectKey(project))+'" aria-current="false"><div class="project-name">'+healthDot(health)+'<div><strong>'+escapeHtml(project.project.name)+'</strong><span>'+escapeHtml(commit?commit.subject:(status?fieldValue(status,"goal")||t().no_commits:t().no_commits))+'</span></div></div><div class="phase"><span class="cell-label">'+escapeHtml(t().updated)+'</span><span class="cell-value">'+escapeHtml(commit?relativeTime(commit.committed_at):"—")+'</span></div><div class="verification"><span class="cell-label">'+escapeHtml(t().dirty)+'</span><span class="cell-value">'+escapeHtml(dirty?t().yes:t().no)+'</span></div><div class="activity"><span class="cell-label">'+escapeHtml(t().next)+'</span><span class="cell-value">'+escapeHtml(next||"—")+'</span></div><div class="cadence-wrap"><span class="cell-label">'+escapeHtml(t().activity_30d)+'</span>'+cadence(project)+'</div><span class="chevron">›</span></button>'}
function overview(){const projects=(data.projects||[]).slice().sort((a,b)=>String((latestCommit(b)||{}).committed_at||"").localeCompare(String((latestCommit(a)||{}).committed_at||"")));document.title="OctoPulse — "+t().overview;return '<section class="hero"><h1>'+escapeHtml(t().portfolio_title)+'</h1><p>'+escapeHtml(t().portfolio_report)+'</p></section>'+renderMetrics()+renderAttention(attentionProject())+'<div class="section-head"><h2>'+escapeHtml(t().projects)+'</h2><span>'+projects.length+'</span></div><section class="projects">'+(projects.length?projects.map(renderRow).join(''):'<div class="empty">'+escapeHtml(t().no_projects)+'</div>')+'</section>'}
function facts(project,status){const git=project.git||{},worktree=git.worktree||{};return '<div class="detail-section"><h2>'+escapeHtml(t().git_facts)+'</h2><div class="fact"><span class="fact-label">'+escapeHtml(t().branch)+'</span><span class="fact-value">'+escapeHtml(git.branch||"—")+'</span></div><div class="fact"><span class="fact-label">'+escapeHtml(t().commit)+'</span><span class="fact-value">'+escapeHtml(git.commit||"—")+'</span></div><div class="fact"><span class="fact-label">'+escapeHtml(t().dirty)+'</span><span class="fact-value">'+escapeHtml(git.dirty?t().yes:t().no)+'</span></div><div class="fact"><span class="fact-label">'+escapeHtml(t().worktree)+'</span><span class="fact-value">'+escapeHtml([worktree.staged||0,worktree.unstaged||0,worktree.untracked||0].join(" / "))+'</span></div></div>'}
function detail(project){const status=projectStatus(project),health=projectHealth(project),risks=project.signals||[],commits=project.history||[],tools=project.activity?.tools||[];document.title="OctoPulse — "+project.project.name;const back=singleProject?"":'<button class="back" type="button" data-overview="true">‹ '+escapeHtml(t().back_overview)+'</button>';return '<section class="detail">'+back+'<div class="detail-top"><div><h1>'+escapeHtml(project.project.name)+'</h1><p class="detail-path">'+escapeHtml(project.project.path)+'</p></div><div>'+healthDot(health)+' '+escapeHtml(health)+'</div></div>'+lead(project)+'<h2>'+escapeHtml(t().uncommitted)+'</h2>'+uncommitted(project)+'<h2>'+escapeHtml(t().completed)+'</h2>'+timeline(commits)+'<h2>'+escapeHtml(t().project_state)+'</h2>'+written(status)+handoff(status)+'<h2>'+escapeHtml(t().signals)+'</h2><ul class="risk-list">'+(risks.length?risks.map(risk=>'<li>'+escapeHtml(signalText(risk))+'</li>').join(''):'<li>'+escapeHtml(t().none)+'</li>')+'</ul><h2>'+escapeHtml(t().recent_activity)+'</h2>'+cadence(project)+'<ul class="tool-list">'+(tools.length?tools.map(tool=>'<li><strong>'+escapeHtml(tool.tool)+'</strong><br><span class="commit-time">'+escapeHtml(String(tool.sessions))+' · '+escapeHtml(tool.last_used_at)+' · '+escapeHtml(tool.last_result||t().unknown)+'</span></li>').join(''):'<li>'+escapeHtml(t().no_activity)+'</li>')+'</ul></section>'}
function bind(){document.querySelectorAll("[data-project]").forEach(button=>button.addEventListener("click",()=>writeState(button.dataset.project)));document.querySelectorAll("[data-overview]").forEach(button=>button.addEventListener("click",()=>writeState("")))}
function render(){const text=t(),key=singleProject?projectKey(data.projects[0]):stateProject(),project=(data.projects||[]).find(item=>projectKey(item)===key);document.documentElement.lang=lang;document.getElementById("overview").hidden=singleProject;document.getElementById("overview").textContent=text.overview;document.getElementById("overview").setAttribute("aria-pressed",String(!project));document.getElementById("zh").setAttribute("aria-pressed",String(lang==="zh-TW"));document.getElementById("en").setAttribute("aria-pressed",String(lang==="en"));document.getElementById("updated").textContent=text.updated+": "+(data.generated_at||"—");document.getElementById("app").innerHTML=project?detail(project):overview();bind()}
document.getElementById("overview").addEventListener("click",()=>writeState(""));document.getElementById("zh").addEventListener("click",()=>{lang="zh-TW";writeState(singleProject?projectKey(data.projects[0]):stateProject(),true)});document.getElementById("en").addEventListener("click",()=>{lang="en";writeState(singleProject?projectKey(data.projects[0]):stateProject(),true)});addEventListener("popstate",render);render();
</script></body></html>""".replace("__PAYLOAD__", payload).replace("__LABELS__", translations).replace("__LANG__", html.escape(language)).replace("__SINGLE__", "true" if single_project else "false")


def project_html(snapshot: dict[str, Any], language: str) -> str:
    return _console_html({"generated_at": snapshot["generated_at"], "projects": [snapshot]}, language, True)


def refresh_project_report(project_root: Path, history: int = 20, legacy_status: str = "auto", language: str = "zh-TW", force: bool = False) -> tuple[dict[str, Any], bool]:
    ensure_local_exclude(project_root)
    snapshot = collect_project_snapshot(project_root, history, legacy_status)
    previous = _read_snapshot(project_root)
    paths = [snapshot_path(project_root), report_dir(project_root) / "latest.md", report_dir(project_root) / "index.html"]
    if not force and previous and previous.get("source_signature") == snapshot["source_signature"] and previous.get("render_language") == language and all(path.exists() for path in paths):
        return previous, True
    report_dir(project_root).mkdir(parents=True, exist_ok=True)
    snapshot["render_language"] = language
    core.write_json(paths[0], snapshot)
    paths[1].write_text(project_markdown(snapshot, language), encoding="utf-8")
    paths[2].write_text(project_html(snapshot, language), encoding="utf-8")
    return snapshot, False


def collect_portfolio(refresh: str = "auto", history: int = 20, legacy_status: str = "auto", language: str = "zh-TW") -> tuple[dict[str, Any], list[str]]:
    config = core.load_config()
    markers, missing_roots = core.discover_markers(config["roots"])
    projects: list[dict[str, Any]] = []
    refreshed: list[str] = []
    for marker in markers:
        project_root = marker.parent.resolve()
        if core.git_root(project_root) != project_root:
            projects.append({"state": "invalid_project_root", "project": {"name": project_root.name, "path": str(project_root)}})
            continue
        snapshot = _read_snapshot(project_root)
        if refresh != "never":
            candidate = collect_project_snapshot(project_root, history, legacy_status)
            changed = snapshot is None or candidate.get("source_signature") != snapshot.get("source_signature")
            if refresh == "all" or changed:
                snapshot, _ = refresh_project_report(project_root, history, legacy_status, language, force=True)
                refreshed.append(str(project_root))
        if snapshot is None:
            projects.append({"state": "missing_project_report", "project": {"name": project_root.name, "path": str(project_root)}})
        else:
            try:
                generated = datetime.fromisoformat(snapshot["generated_at"].replace("Z", "+00:00"))
                if generated < datetime.now().astimezone() - timedelta(days=SNAPSHOT_STALE_DAYS):
                    snapshot = {**snapshot, "signals": [*snapshot.get("signals", []), "snapshot_stale"]}
            except (KeyError, TypeError, ValueError):
                snapshot = {**snapshot, "signals": [*snapshot.get("signals", []), "snapshot_stale"]}
            projects.append(snapshot)
    for path in missing_roots:
        projects.append({"state": "missing_root", "project": {"name": Path(path).name, "path": path}})
    projects.sort(key=lambda item: ((item.get("history") or [{}])[0].get("committed_at") or ""), reverse=True)
    portfolio = {"schema_version": 1, "generated_at": core.now_iso(), "projects": projects}
    signature_entries = [
        {
            "project": item["project"],
            "state": item.get("state"),
            "source_signature": item.get("source_signature"),
            "signals": item.get("signals", []),
        }
        for item in projects
    ]
    portfolio["source_signature"] = core.fingerprint(signature_entries)
    portfolio["render_language"] = language
    return portfolio, refreshed


def portfolio_markdown(portfolio: dict[str, Any], language: str) -> str:
    t = labels(language)
    snapshots = [item for item in portfolio["projects"] if "marker" in item]
    health_counts = Counter((item["marker"].get("status") or {}).get("health", item["marker"]["state"]) for item in snapshots)
    verification_counts = Counter((item["marker"].get("status") or {}).get("verification", {}).get("status", "unknown") for item in snapshots)
    dirty = [item["project"]["name"] for item in snapshots if item.get("git", {}).get("dirty")]
    tools = sorted((tool for item in snapshots for tool in item.get("activity", {}).get("tools", [])), key=lambda item: item.get("last_used_at", ""), reverse=True)
    risk = [item["project"]["name"] for item in snapshots if item.get("signals")]
    health_summary = ", ".join(f"{key}={value}" for key, value in sorted(health_counts.items())) or t["none"]
    verification_summary = ", ".join(f"{key}={value}" for key, value in sorted(verification_counts.items())) or t["none"]
    tool_summary = ", ".join(f"{item['tool']} ({item['last_used_at']})" for item in tools) or t["unknown"]
    lines = [f"# {t['portfolio_report']}", "", f"- {t['generated']}: {portfolio['generated_at']}", f"- {t['projects']}: {len(portfolio['projects'])}", f"- {t['health']}: {health_summary}", f"- {t['verification']}: {verification_summary}", f"- {t['dirty']}: {', '.join(dirty) or t['none']}", f"- {t['signals']}: {', '.join(risk) or t['none']}", f"- {t['tools']}: {tool_summary}", ""]
    for item in portfolio["projects"]:
        project = item["project"]
        lines.extend([f"## {project['name']}", "", f"- path: `{project['path']}`"])
        if "marker" not in item:
            lines.extend([f"- state: {item['state']}", ""])
            continue
        status = item["marker"].get("status")
        if status:
            activity = item.get("activity", {})
            activity_summary = ", ".join(f"{tool['tool']} ({tool['last_used_at']})" for tool in activity.get("tools", [])) or activity.get("state", t["unknown"])
            handoff = status.get("handoff")
            handoff_summary = f"{handoff['tool']} · {handoff['created_at']} · {', '.join(handoff['read_first']) or t['none']}" if handoff else t["none"]
            latest = (item.get("history") or [{}])[0]
            goal = _visible_field(status.get("goal"), core.DEFAULT_GOAL)
            next_action = _visible_field(status.get("next_action"), core.DEFAULT_NEXT)
            lines.append(f"- {t['health']}: {status['health']} · {t['phase']}: {status['phase']} · {t['where']}: {latest.get('subject') or t['no_commits']}")
            if goal:
                lines.append(f"- {t['goal']}: {goal}")
            if next_action:
                lines.append(f"- {t['next']}: {next_action}")
            lines.extend([f"- {t['verification']}: {status['verification']['status']} · {t['dirty']}: {t['yes'] if item['git'].get('dirty') else t['no']}", f"- {t['handoff']}: {handoff_summary}", f"- {t['signals']}: {', '.join(_signal_text(signal, language) for signal in item['signals']) or t['none']}", f"- {t['tools']}: {activity_summary}"])
        else:
            lines.append(f"- state: {item['marker']['state']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _legacy_portfolio_html(portfolio: dict[str, Any]) -> str:
    payload = json.dumps(portfolio, ensure_ascii=False).replace("</", "<\\/")
    translations = json.dumps(LABELS, ensure_ascii=False)
    return f"""<!doctype html><html lang=\"zh-TW\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>OctoPulse Portfolio</title>
<style>:root{{color-scheme:light dark}}body{{font-family:system-ui;margin:0;color:CanvasText;background:Canvas}}header,main{{max-width:1100px;margin:auto;padding:1rem}}nav{{display:flex;gap:.5rem;flex-wrap:wrap}}button{{font:inherit;padding:.45rem .7rem}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.75rem}}.card{{border:1px solid GrayText;border-radius:.5rem;padding:.75rem}}.muted{{color:GrayText}}.signal{{color:darkorange}}pre{{white-space:pre-wrap}}@media(max-width:600px){{header,main{{padding:.75rem}}.cards{{grid-template-columns:1fr}}}}</style>
<header><nav><button id=\"overview\"></button><button id=\"zh\">繁中</button><button id=\"en\">English</button></nav><nav id=\"projects\"></nav></header><main id=\"content\"></main>
<script>const data={payload};const labels={translations};let lang=new URLSearchParams(location.search).get('lang')==='en'?'en':'zh-TW';const text=()=>labels[lang];function projectName(p){{return p.project.name}}function setState(name){{const u=new URL(location);u.searchParams.set('lang',lang);u.hash=name?'project='+encodeURIComponent(name):'';history.pushState(null,'',u);render()}}function esc(v){{const n=document.createElement('span');n.textContent=v??'—';return n.innerHTML}}function render(){{const t=text();document.documentElement.lang=lang;overview.textContent=t.overview;projects.innerHTML='';data.projects.forEach(p=>{{const b=document.createElement('button');b.textContent=projectName(p);b.onclick=()=>setState(projectName(p));projects.append(b)}});const name=new URLSearchParams(location.hash.slice(1)).get('project');const p=data.projects.find(x=>projectName(x)===name);if(!p){{const counts={{}};data.projects.forEach(x=>{{const h=x.marker?.status?.health||x.state||x.marker?.state||t.unknown;counts[h]=(counts[h]||0)+1}});content.innerHTML='<h1>'+esc(t.portfolio_report)+'</h1><p class=\"muted\">'+esc(t.updated)+': '+esc(data.generated_at)+'</p><section class=\"cards\">'+Object.entries(counts).map(([k,v])=>'<div class=\"card\"><strong>'+esc(k)+'</strong><br>'+esc(v)+'</div>').join('')+'</section><h2>'+esc(t.projects)+'</h2>'+data.projects.map(x=>{{const s=x.marker?.status;return '<article class=\"card\"><h3>'+esc(projectName(x))+'</h3><p>'+esc(s?.goal||x.state||x.marker?.state)+'</p><p class=\"muted\">'+esc(s?.next_action||'')+'</p></article>'}}).join('');return}}const s=p.marker?.status;content.innerHTML='<h1>'+esc(projectName(p))+'</h1><p class=\"muted\">'+esc(p.project.path)+'</p>'+(!s?'<p>'+esc(p.state||p.marker?.state)+'</p>':'<dl><dt>'+esc(t.phase)+'</dt><dd>'+esc(s.phase)+'</dd><dt>'+esc(t.health)+'</dt><dd>'+esc(s.health)+'</dd><dt>'+esc(t.goal)+'</dt><dd>'+esc(s.goal)+'</dd><dt>'+esc(t.summary)+'</dt><dd>'+esc(s.summary)+'</dd><dt>'+esc(t.next)+'</dt><dd>'+esc(s.next_action)+'</dd><dt>'+esc(t.verification)+'</dt><dd>'+esc(s.verification.status)+'</dd></dl><h2>'+esc(t.signals)+'</h2><p class=\"signal\">'+esc((p.signals||[]).join(', ')||t.none)+'</p><h2>'+esc(t.history)+'</h2><ul>'+p.history.map(h=>'<li><code>'+esc(h.commit)+'</code> '+esc(h.subject)+'</li>').join('')+'</ul><h2>'+esc(t.tools)+'</h2><pre>'+esc(JSON.stringify(p.activity,null,2))+'</pre>')}}overview.onclick=()=>setState('');zh.onclick=()=>{{lang='zh-TW';setState(new URLSearchParams(location.hash.slice(1)).get('project')||'')}};en.onclick=()=>{{lang='en';setState(new URLSearchParams(location.hash.slice(1)).get('project')||'')}};addEventListener('popstate',render);render();</script></html>\n"""


def portfolio_html(portfolio: dict[str, Any]) -> str:
    return _console_html(portfolio, portfolio.get("render_language", "zh-TW"), False)


def write_portfolio_report(portfolio: dict[str, Any], output: Path, language: str, report_format: str = "both") -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / "projects.json", output / "latest.md", output / "index.html"]
    previous, error = core.read_json(paths[0])
    expected = [paths[0]]
    if report_format in {"markdown", "both"}:
        expected.append(paths[1])
    if report_format in {"html", "both"}:
        expected.append(paths[2])
    if error is None and isinstance(previous, dict) and previous.get("source_signature") == portfolio.get("source_signature") and previous.get("render_language") == language and all(path.exists() for path in expected):
        return []
    core.write_json(paths[0], portfolio)
    written = [paths[0]]
    if report_format in {"markdown", "both"}:
        paths[1].write_text(portfolio_markdown(portfolio, language), encoding="utf-8")
        written.append(paths[1])
    if report_format in {"html", "both"}:
        paths[2].write_text(portfolio_html(portfolio), encoding="utf-8")
        written.append(paths[2])
    return written
