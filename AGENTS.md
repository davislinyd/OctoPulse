# OctoPulse v2 Agent Rules

OctoPulse v2 uses `.otcopulse` as the sole project progress source.

## Context boundary

- Before reading progress, run `octopulse context` from the current Git project.
- Read only `.otcopulse` and lightweight Git facts for ordinary project status work.
- Do not read project source, conversation history, generated reports, `PROJECT_STATUS.md`, or `.ai/status.json` to infer progress.
- Use `octopulse report --explain` only when the user asks for cross-project status.

## Project protocol

- If the marker is missing, empty, or invalid, explain it and obtain approval before `octopulse init --yes` or another write.
- After non-trivial work, update `.otcopulse` only when its factual status changes, then run `octopulse validate .otcopulse`.
- Status data must not contain secrets, tokens, passwords, raw tickets, raw logs, or private dumps.
- For an old project that should remain visible without active work, run `octopulse archive --yes --reason "..."`; this writes a `paused` / `stale` pulse without reading source code.

## Git operations

- Inspect `git status --short --branch` and `git remote -v` before pushes, tags, or releases.
- Prefer the user's internal `git.insea.io` remote when present.
- Do not assume `origin` is the intended GitLab remote.
