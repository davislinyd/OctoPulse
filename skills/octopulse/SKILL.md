---
name: OctoPulse
description: Use for project progress status, `.otcopulse` setup or validation, migration from legacy OctoPulse status, and marker-only cross-project reports.
---

# OctoPulse

Run `octopulse context` before reading project progress. It reads only the Git root and `.otcopulse`.

- `valid`: use only `.otcopulse` as the current project pulse. Update it after non-trivial work only when goal, summary, next action, verification, or attention changes; then run `octopulse validate .otcopulse`.
- `missing`, `uninitialized`, or `invalid`: explain the state and ask the user before any write. After approval use `octopulse init --yes`; never infer status by scanning source code.
- For a retired project that should remain visible, ask approval and run `octopulse archive --yes --reason "..."`. It writes a `paused` / `stale` marker without reading source or legacy status files.
- Use `octopulse report --explain` only for cross-project status. Do not load generated reports into ordinary project sessions.

Read [the schema reference](references/status-schema.md) only when creating or repairing a marker.
