# OctoPulse Agent Rules

OctoPulse is a central status hub. Keep the boundary between central summaries and managed project source trees explicit.

## Default Reading Scope

- A top-level Agent should read only `projects.yaml`, `state/projects.json`, and `reports/latest.md` by default.
- A top-level Agent should not read managed project source code by default.
- A top-level Agent should not read `.ai/history` by default.
- A top-level Agent may read a specific project's `PROJECT_STATUS.md` only when the user asks for more detail about that project.
- A top-level Agent may inspect source code only when the user asks to implement, debug, or review that specific project.

## Project Agent Responsibilities

- Each project Agent should update only that project's `PROJECT_STATUS.md` and `.ai/status.json`.
- Project Agents should not directly modify OctoPulse central outputs.
- Status files must not contain secrets, cookies, tokens, raw ticket data, raw logs, or private dumps.
- Keep `latest_summary` short enough for a top-level Agent to scan across many projects.

## Recommended Project Agent Protocol

Start of non-trivial work:

- Read local `AGENTS.md` if present.
- Read `PROJECT_STATUS.md` if present.
- Read `.ai/status.json` if present.
- Check `git status --short --branch`.

End of non-trivial work:

- Update `PROJECT_STATUS.md`.
- Update `.ai/status.json`.
- Record current goal, latest changes, verification, git status, next action, and timestamp.

## OctoPulse Central Output

- Use `python tools/validate_status.py <project>/.ai/status.json` to validate one project pulse.
- Use `python tools/scan_projects.py` to regenerate `state/projects.json`, `reports/latest.md`, and `dashboard/index.html`.
- The scanner must not run `git fetch`.
- The scanner must not read project source code.
- The scanner must not read `.ai/history`.

## Git Operations

- Inspect `git status --short --branch` and `git remote -v` before pushes, tags, or releases.
- Prefer the user's internal `git.insea.io` remote when present.
- Do not assume `origin` is the intended GitLab remote.
