# OctoPulse Implementation Plan

## Summary

OctoPulse is a lightweight cross-project status hub for AI-assisted development workflows.

The problem it solves: the user works across many projects in different folders, often with separate AI Agent conversations. It becomes hard to remember each project's latest progress. OctoPulse lets every project publish a small local status pulse, then collects those pulses into a concise report and static dashboard for humans and AI agents.

Core design:

- Each project owns and updates only its own status files.
- OctoPulse reads short status files and produces centralized output.
- The top-level Agent reads OctoPulse summaries by default, not full project source code.
- v1 uses only files, Python standard library, Markdown, JSON, YAML-like parsing, and static HTML.

Recommended repo/folder name:

```text
octopulse
```

Tagline:

```text
OctoPulse: one pulse check for every project.
```

## Repository Structure

OctoPulse v1 should create this structure:

```text
octopulse/
  AGENTS.md
  README.md
  projects.yaml
  schemas/
    status.schema.json
  tools/
    validate_status.py
    scan_projects.py
  state/
    projects.json
  reports/
    latest.md
  dashboard/
    index.html
```

Each managed project should expose:

```text
<Project>/
  PROJECT_STATUS.md
  .ai/
    status.json
```

## Status Pulse Schema

Each project's `.ai/status.json` is the primary short status pulse read by OctoPulse.

Example:

```json
{
  "name": "Project Name",
  "path": "/absolute/project/path",
  "last_updated": "2026-05-11T10:00:00+08:00",
  "phase": "planning",
  "health": "active",
  "status_confidence": "medium",
  "status_source": "agent_reported",
  "current_goal": "目前正在做什麼",
  "latest_summary": "最新狀態，最多 1-3 句",
  "next_action": "下一步",
  "git": {
    "branch": "main",
    "dirty": false,
    "remote_tracking": "origin/main",
    "commit": "abc1234"
  },
  "verification": {
    "status": "passed",
    "last_commands": ["npm run build"],
    "last_verified_at": "2026-05-11T09:50:00+08:00"
  },
  "attention": []
}
```

Allowed enum values:

- `phase`: `planning`, `implementation`, `verification`, `maintenance`, `paused`
- `health`: `active`, `stable`, `needs_attention`, `blocked`, `stale`
- `status_confidence`: `high`, `medium`, `low`
- `status_source`: `agent_reported`, `scanner_verified`, `manual`
- `verification.status`: `passed`, `failed`, `not_run`, `partial`

Required behavior:

- Do not store secrets, cookies, tokens, raw ticket data, or raw logs in status files.
- Keep `latest_summary` short enough for a top-level Agent to read across many projects.
- Use `PROJECT_STATUS.md` for richer human-readable context.
- Use `.ai/status.json` for stable machine-readable status.

## Project Index

`projects.yaml` is OctoPulse's only project index.

Example:

```yaml
projects:
  - name: Project Name
    path: /absolute/project/path
    status_file: .ai/status.json
    detail_file: PROJECT_STATUS.md
```

Requirements:

- Support absolute paths.
- Support relative paths.
- Relative paths are resolved from the OctoPulse repo root.
- v1 can use a small purpose-built parser for this limited YAML shape instead of adding dependencies.

## CLI Tools

### `tools/validate_status.py`

Command:

```bash
python tools/validate_status.py path/to/status.json
```

Responsibilities:

- Read the JSON file.
- Validate required top-level fields.
- Validate required `git` fields.
- Validate required `verification` fields.
- Validate enum values.
- Print clear errors and exit non-zero on failure.
- Print `validation passed` and exit zero on success.

### `tools/scan_projects.py`

Command:

```bash
python tools/scan_projects.py
```

Responsibilities:

- Read `projects.yaml`.
- Resolve each project path.
- Read each project's `.ai/status.json`.
- Validate each status pulse.
- Run lightweight local git checks where possible:
  - current branch
  - dirty state
  - short commit
  - upstream or remote tracking if available
- Do not run `git fetch`.
- Do not read project source code.
- Do not read `.ai/history`.
- Write `state/projects.json`.
- Write `reports/latest.md`.
- Write `dashboard/index.html`.

Derived status rules:

- Project path does not exist: `missing_project`
- Status file does not exist: `missing_status`
- JSON invalid or schema invalid: `invalid_status`
- `last_updated` older than 24 hours: `stale`
- `health=blocked`: `blocked`
- `verification.status=failed`: `needs_attention`
- Git dirty and status file appears older than current repo activity: `needs_attention`
- Otherwise use the project's declared `health`

## Generated Outputs

### `state/projects.json`

Machine-readable aggregate output for the top-level Agent.

It should include:

- scan timestamp
- project list
- declared status fields
- derived status
- validation errors, if any
- lightweight git facts, if available

### `reports/latest.md`

Human and AI-readable summary report.

Group projects in this order:

```text
Blocked
Needs Attention
Active
Stable
Stale
Missing Status
Invalid Status
```

Each project entry should show only:

- project name
- derived status
- declared health
- current goal
- latest summary
- next action
- last updated
- branch / dirty / commit
- verification status
- attention items

Do not dump full JSON into the report.

### `dashboard/index.html`

Static dashboard.

Requirements:

- Open directly in a browser.
- No server required.
- No external CDN.
- Show scan timestamp.
- Group projects by derived status.
- Use simple, readable visual styling.
- Display project name, goal, latest summary, next action, update time, git state, verification state, and attention items.

## Agent Rules

Create `AGENTS.md` for OctoPulse with these rules:

- A top-level Agent should read only `projects.yaml`, `state/projects.json`, and `reports/latest.md` by default.
- A top-level Agent should not read managed project source code by default.
- A top-level Agent should not read `.ai/history` by default.
- A top-level Agent may read a specific project's `PROJECT_STATUS.md` only when the user asks for more detail about that project.
- A top-level Agent may inspect source code only when the user asks to implement, debug, or review that specific project.
- Each project Agent should update only that project's `PROJECT_STATUS.md` and `.ai/status.json`.
- Project Agents should not directly modify OctoPulse central outputs.

Recommended project Agent protocol:

```text
Start of non-trivial work:
- Read local AGENTS.md if present.
- Read PROJECT_STATUS.md if present.
- Read .ai/status.json if present.
- Check git status --short --branch.

End of non-trivial work:
- Update PROJECT_STATUS.md.
- Update .ai/status.json.
- Record current goal, latest changes, verification, git status, next action, and timestamp.
```

## README Requirements

`README.md` should explain:

- What OctoPulse is.
- The problem it solves.
- How each project publishes a status pulse.
- How to configure `projects.yaml`.
- How to validate one status file.
- How to scan all projects.
- How to read `reports/latest.md`.
- How to open `dashboard/index.html`.
- What v1 intentionally does not do.

v1 non-goals:

- No persistent web server.
- No database.
- No remote fetch or remote parity enforcement.
- No automatic reading of full source code.
- No full conversation history import.
- No CI or pre-commit enforcement yet.
- No multi-branch status model yet.

## Managed Projects

The bootstrap placeholder has been removed after onboarding real project status entries.

`projects.yaml` should point only to actual managed projects.

## Acceptance Criteria

After implementation, these commands should pass:

```bash
python tools/validate_status.py /absolute/project/path/.ai/status.json
python tools/scan_projects.py
```

The scan command should produce or update:

```text
state/projects.json
reports/latest.md
dashboard/index.html
```

The final implementation report should include:

- Main files created.
- How to run validation.
- How to run scanning.
- Verification result.
- Any known limitations or recommended v2 work.

## V2 Ideas

Defer these until v1 is stable:

- `octopulse` command wrapper.
- Local web server.
- Search/filter UI in dashboard.
- Remote parity checks with explicit opt-in fetch.
- CI or pre-commit warnings.
- Multi-worktree or multi-branch status files.
- Historical trend view.
- Scheduled scan automation.
