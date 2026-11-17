# OctoPulse v3 Agent Rules

OctoPulse v3 uses `.octopulse` as the sole project progress source.

## Context boundary

- Before reading progress, run `octopulse status` from the current Git project. Use `octopulse status --json` for the machine-readable pulse.
- The pulse plus lightweight Git facts are enough for ordinary project status. Do not read project source, conversation history, generated reports, `PROJECT_STATUS.md`, or `.ai/status.json` to infer progress.
- Use `octopulse report --explain` only when the user asks for cross-project status.

## Project protocol

- When the user does not explicitly ask to enroll a project or change its goal, summary, next action, verification, or attention, only read reports. Run `octopulse status` here and `octopulse portfolio report --refresh auto --explain` for every registered project. Do not ask for a goal or next action, and do not write a marker.
- When the user asks to put this project's progress into OctoPulse, enroll it in the same turn with `octopulse update --yes --tool grok`. Pass `--goal`, `--summary`, or `--next` only when the user stated them. Omitted values use the CLI placeholders. For schema v2 this upgrades the marker and keeps existing fields. For a legacy `.otcopulse` filename, run `octopulse migrate-marker --yes` first. Do not scan the repository to invent a goal or next action.
- If the marker is invalid, explain the errors and obtain approval before repair.
- After enrollment, the installed hooks refresh reports on later turns. The project report is `.octopulse-reports/index.html`. The portfolio report is `~/.config/octopulse/reports/index.html`.
- After other non-trivial work, run `octopulse update` only when goal, summary, next action, verification, or attention changes, and pass `--tool grok` on that update.
- Status data must not contain secrets, tokens, passwords, raw tickets, raw logs, or private dumps.
- For an old project that should remain visible without active work, run `octopulse archive --yes --reason "..."`. It writes a `paused` / `stale` pulse without reading source code.

## Git operations

- Inspect `git status --short --branch` and `git remote -v` before pushes, tags, or releases.
- Prefer the user's internal `git.insea.io` remote when present.
- Do not assume `origin` is the intended GitLab remote.
