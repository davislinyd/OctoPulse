"""Project snapshots and report renderers for OctoPulse."""

from __future__ import annotations

import html
import json
import fcntl
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
TOOLS = {"codex", "claude", "antigravity"}
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
    for line in porcelain.splitlines():
        if line.startswith("??"):
            counts["untracked"] += 1
            continue
        if len(line) >= 2:
            if line[0] != " ":
                counts["staged"] += 1
            if line[1] != " ":
                counts["unstaged"] += 1
    return counts


def _history(project_root: Path, count: int) -> list[dict[str, str]]:
    count = max(1, min(count, 50))
    output = _git(project_root, ["log", f"--max-count={count}", "--date=iso-strict", "--pretty=format:%h%x1f%ad%x1f%s"])
    entries = []
    for line in output.splitlines():
        values = line.split("\x1f", 2)
        if len(values) == 3:
            entries.append({"commit": values[0], "committed_at": values[1], "subject": values[2][:240]})
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
        return {"state": "unknown", "tools": []}
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        item = grouped.setdefault(event["tool"], {"tool": event["tool"], "sessions": 0, "last_used_at": event["timestamp"], "last_result": ""})
        item["last_used_at"] = max(item["last_used_at"], event["timestamp"])
        if event["event"] == "finish":
            item["sessions"] += 1
            item["last_result"] = event["result"]
    return {"state": "recorded", "tools": sorted(grouped.values(), key=lambda item: item["tool"])}


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


def collect_project_snapshot(project_root: Path, history: int = 10, legacy_status: str = "auto") -> dict[str, Any]:
    project_root = project_root.resolve()
    inspection = core.inspect_marker(project_root / core.MARKER_NAME)
    status = inspection.get("payload") if inspection["state"] == "valid" else None
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
        "history": _history(project_root, history),
        "legacy_context": legacy,
        "activity": _activity_summary(events),
    }
    snapshot["signals"] = _signals(status, git, legacy)
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


def project_markdown(snapshot: dict[str, Any], language: str) -> str:
    t = labels(language)
    status = snapshot["marker"].get("status")
    git = snapshot["git"]
    lines = [f"# {t['project_report']}: {snapshot['project']['name']}", "", f"- {t['generated']}: {snapshot['generated_at']}", f"- {t['updated']}: {_value(status.get('last_updated') if status else None)}", f"- {t['phase']}: {_value(status.get('phase') if status else snapshot['marker']['state'])}", f"- {t['health']}: {_value(status.get('health') if status else 'unknown')}", ""]
    if status:
        lines.extend([f"## {t['overview']}", "", f"- {t['goal']}: {status['goal']}", f"- {t['summary']}: {status['summary']}", f"- {t['next']}: {status['next_action']}", f"- {t['verification']}: {status['verification']['status']} ({_value(status['verification']['last_command'])})", f"- {t['attention']}: {', '.join(status['attention']) or t['none']}", ""])
    signal_lines = [f"- {signal}" for signal in snapshot["signals"]] or [f"- {t['none']}"]
    lines.extend([f"## {t['git']}", "", f"- {t['branch']}: {_value(git.get('branch'))}", f"- {t['commit']}: {_value(git.get('commit'))}", f"- {t['upstream']}: {_value(git.get('upstream'))}", f"- {t['dirty']}: {t['yes'] if git.get('dirty') else t['no']}", f"- {t['worktree']}: staged / unstaged / untracked = {git['worktree']['staged']} / {git['worktree']['unstaged']} / {git['worktree']['untracked']}", "", f"## {t['signals']}", "", *signal_lines, "", f"## {t['tools']}", ""])
    tools = snapshot["activity"]["tools"]
    lines.extend([f"- {item['tool']}: {item['sessions']} sessions, {item['last_used_at']}, {item['last_result'] or t['unknown']}" for item in tools] or [f"- {t['unknown']}"])
    lines.extend(["", f"## {t['history']}", ""])
    lines.extend([f"- `{item['commit']}` {item['committed_at']}: {item['subject']}" for item in snapshot["history"]] or [f"- {t['none']}"])
    if snapshot["legacy_context"]:
        lines.extend(["", f"## {t['legacy']}", "", f"- {json.dumps(snapshot['legacy_context'], ensure_ascii=False)}"])
    return "\n".join(lines).rstrip() + "\n"


def project_html(snapshot: dict[str, Any], language: str) -> str:
    body = html.escape(project_markdown(snapshot, language))
    return f"""<!doctype html><html lang=\"{html.escape(language)}\"><meta charset=\"utf-8\"><title>{html.escape(snapshot['project']['name'])}</title><style>body{{font-family:system-ui;margin:2rem;line-height:1.5;max-width:960px}}pre{{white-space:pre-wrap}}</style><pre>{body}</pre></html>\n"""


def refresh_project_report(project_root: Path, history: int = 10, legacy_status: str = "auto", language: str = "zh-TW", force: bool = False) -> tuple[dict[str, Any], bool]:
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


def collect_portfolio(refresh: str = "auto", history: int = 10, legacy_status: str = "auto", language: str = "zh-TW") -> tuple[dict[str, Any], list[str]]:
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
            lines.extend([f"- {t['health']}: {status['health']} · {t['phase']}: {status['phase']} · {t['updated']}: {status['last_updated']}", f"- {t['goal']}: {status['goal']}", f"- {t['next']}: {status['next_action']}", f"- {t['verification']}: {status['verification']['status']} · {t['dirty']}: {t['yes'] if item['git'].get('dirty') else t['no']}", f"- {t['signals']}: {', '.join(item['signals']) or t['none']}", f"- {t['tools']}: {activity_summary}"])
        else:
            lines.append(f"- state: {item['marker']['state']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def portfolio_html(portfolio: dict[str, Any]) -> str:
    payload = json.dumps(portfolio, ensure_ascii=False).replace("</", "<\\/")
    translations = json.dumps(LABELS, ensure_ascii=False)
    return f"""<!doctype html><html lang=\"zh-TW\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>OctoPulse Portfolio</title>
<style>:root{{color-scheme:light dark}}body{{font-family:system-ui;margin:0;color:CanvasText;background:Canvas}}header,main{{max-width:1100px;margin:auto;padding:1rem}}nav{{display:flex;gap:.5rem;flex-wrap:wrap}}button{{font:inherit;padding:.45rem .7rem}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.75rem}}.card{{border:1px solid GrayText;border-radius:.5rem;padding:.75rem}}.muted{{color:GrayText}}.signal{{color:darkorange}}pre{{white-space:pre-wrap}}@media(max-width:600px){{header,main{{padding:.75rem}}.cards{{grid-template-columns:1fr}}}}</style>
<header><nav><button id=\"overview\"></button><button id=\"zh\">繁中</button><button id=\"en\">English</button></nav><nav id=\"projects\"></nav></header><main id=\"content\"></main>
<script>const data={payload};const labels={translations};let lang=new URLSearchParams(location.search).get('lang')==='en'?'en':'zh-TW';const text=()=>labels[lang];function projectName(p){{return p.project.name}}function setState(name){{const u=new URL(location);u.searchParams.set('lang',lang);u.hash=name?'project='+encodeURIComponent(name):'';history.pushState(null,'',u);render()}}function esc(v){{const n=document.createElement('span');n.textContent=v??'—';return n.innerHTML}}function render(){{const t=text();document.documentElement.lang=lang;overview.textContent=t.overview;projects.innerHTML='';data.projects.forEach(p=>{{const b=document.createElement('button');b.textContent=projectName(p);b.onclick=()=>setState(projectName(p));projects.append(b)}});const name=new URLSearchParams(location.hash.slice(1)).get('project');const p=data.projects.find(x=>projectName(x)===name);if(!p){{const counts={{}};data.projects.forEach(x=>{{const h=x.marker?.status?.health||x.state||x.marker?.state||t.unknown;counts[h]=(counts[h]||0)+1}});content.innerHTML='<h1>'+esc(t.portfolio_report)+'</h1><p class=\"muted\">'+esc(t.updated)+': '+esc(data.generated_at)+'</p><section class=\"cards\">'+Object.entries(counts).map(([k,v])=>'<div class=\"card\"><strong>'+esc(k)+'</strong><br>'+esc(v)+'</div>').join('')+'</section><h2>'+esc(t.projects)+'</h2>'+data.projects.map(x=>{{const s=x.marker?.status;return '<article class=\"card\"><h3>'+esc(projectName(x))+'</h3><p>'+esc(s?.goal||x.state||x.marker?.state)+'</p><p class=\"muted\">'+esc(s?.next_action||'')+'</p></article>'}}).join('');return}}const s=p.marker?.status;content.innerHTML='<h1>'+esc(projectName(p))+'</h1><p class=\"muted\">'+esc(p.project.path)+'</p>'+(!s?'<p>'+esc(p.state||p.marker?.state)+'</p>':'<dl><dt>'+esc(t.phase)+'</dt><dd>'+esc(s.phase)+'</dd><dt>'+esc(t.health)+'</dt><dd>'+esc(s.health)+'</dd><dt>'+esc(t.goal)+'</dt><dd>'+esc(s.goal)+'</dd><dt>'+esc(t.summary)+'</dt><dd>'+esc(s.summary)+'</dd><dt>'+esc(t.next)+'</dt><dd>'+esc(s.next_action)+'</dd><dt>'+esc(t.verification)+'</dt><dd>'+esc(s.verification.status)+'</dd></dl><h2>'+esc(t.signals)+'</h2><p class=\"signal\">'+esc((p.signals||[]).join(', ')||t.none)+'</p><h2>'+esc(t.history)+'</h2><ul>'+p.history.map(h=>'<li><code>'+esc(h.commit)+'</code> '+esc(h.subject)+'</li>').join('')+'</ul><h2>'+esc(t.tools)+'</h2><pre>'+esc(JSON.stringify(p.activity,null,2))+'</pre>')}}overview.onclick=()=>setState('');zh.onclick=()=>{{lang='zh-TW';setState(new URLSearchParams(location.hash.slice(1)).get('project')||'')}};en.onclick=()=>{{lang='en';setState(new URLSearchParams(location.hash.slice(1)).get('project')||'')}};addEventListener('popstate',render);render();</script></html>\n"""


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
