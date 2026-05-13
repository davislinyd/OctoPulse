# OctoPulse

OctoPulse is a lightweight cross-project status hub for AI-assisted development workflows.

It lets each project publish one short local status pulse, then collects those pulses into a concise report and a static dashboard. The goal is to help humans and top-level agents understand project state without reading every project source tree or conversation history.

## What It Solves

When work is spread across many repositories and AI agent conversations, the latest state of each project becomes hard to recover. OctoPulse gives every project a small, predictable status surface:

- `PROJECT_STATUS.md` for human-readable context.
- `.ai/status.json` for machine-readable status.

OctoPulse reads those files, validates them, checks lightweight git facts, and writes centralized outputs.

## Repository Layout

```text
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
examples/
  example-project/
    PROJECT_STATUS.md
    .ai/
      status.json
```

## Status Pulse

Each managed project should expose:

```text
PROJECT_STATUS.md
.ai/status.json
```

The `.ai/status.json` file is the stable machine-readable pulse. Keep it short, current, and sanitized. Do not store secrets, cookies, tokens, raw ticket data, raw logs, or private dumps in status files.

Required enums:

- `phase`: `planning`, `implementation`, `verification`, `maintenance`, `paused`
- `health`: `active`, `stable`, `needs_attention`, `blocked`, `stale`
- `status_confidence`: `high`, `medium`, `low`
- `status_source`: `agent_reported`, `scanner_verified`, `manual`
- `verification.status`: `passed`, `failed`, `not_run`, `partial`

See [schemas/status.schema.json](schemas/status.schema.json) and [examples/example-project/.ai/status.json](examples/example-project/.ai/status.json).

## Configure Projects

Edit [projects.yaml](projects.yaml):

```yaml
projects:
  - name: Example Project
    path: ./examples/example-project
    status_file: .ai/status.json
    detail_file: PROJECT_STATUS.md
```

`path` may be absolute or relative. Relative project paths are resolved from the OctoPulse repository root. `status_file` and `detail_file` may also be absolute, but are normally relative to the project path.

The v1 parser intentionally supports only this small YAML shape, so no extra dependency is required.

## Validate One Status File

```bash
python tools/validate_status.py examples/example-project/.ai/status.json
```

Expected success output:

```text
validation passed
```

Validation checks required fields, nested `git` and `verification` fields, enum values, arrays, booleans, and ISO timestamp shape.

## Scan All Projects

```bash
python tools/scan_projects.py
```

The scanner:

- Reads `projects.yaml`.
- Resolves project paths.
- Reads each `.ai/status.json`.
- Validates each status pulse.
- Runs lightweight local git checks where possible.
- Does not run `git fetch`.
- Does not read project source code.
- Does not read `.ai/history`.

Generated outputs:

```text
state/projects.json
reports/latest.md
dashboard/index.html
```

## Read The Report

Open [reports/latest.md](reports/latest.md) after scanning. It groups projects by derived status:

- Blocked
- Needs Attention
- Active
- Stable
- Stale
- Missing Project
- Missing Status
- Invalid Status

Each entry stays concise: project name, status, goal, summary, next action, update time, git state, verification state, and attention items.

## Open The Dashboard

Open [dashboard/index.html](dashboard/index.html) directly in a browser. No server, CDN, database, or build step is required.

## V1 Non-Goals

- No persistent web server.
- No database.
- No remote fetch or remote parity enforcement.
- No automatic reading of full source code.
- No full conversation history import.
- No CI or pre-commit enforcement yet.
- No multi-branch status model yet.

## Recommended Agent Workflow

At the end of non-trivial project work, update that project's:

- `PROJECT_STATUS.md`
- `.ai/status.json`

Then run OctoPulse scanning from this repository to refresh the central outputs.

## Codex Reminder Hook

OctoPulse includes a Codex `UserPromptSubmit` helper:

```text
tools/octopulse_codex_hook.py
```

The hook reads Codex hook JSON from stdin, checks the current `cwd`, and returns `additionalContext` only when the current project is managed by OctoPulse or already has OctoPulse status files.

It does not block work, edit project files, read source code, or regenerate central outputs. It only reminds the agent to update project-local status files at the end of non-trivial work.
