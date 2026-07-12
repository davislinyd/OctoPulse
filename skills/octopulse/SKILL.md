---
name: OctoPulse
description: Use for OctoPulse project status, per-project reports, AI tool activity, and portfolio reports across registered projects.
---

# OctoPulse

Run `octopulse context` before reading project progress. It reads only the Git root and `.otcopulse`.

- `valid`: use `.otcopulse` as the current project pulse. Update it after non-trivial work only when goal, summary, next action, verification, or attention changes; then run `octopulse validate .otcopulse`.
- `missing`: if the user explicitly requested OctoPulse initialization, run `octopulse init --yes` in the same turn after `context`; otherwise explain the state and ask before writing. `uninitialized` means the empty marker already exists: do not recreate it or infer its semantic status. `invalid` always requires approval before repair. Never infer status by scanning source code.
- For a retired project that should remain visible, ask approval and run `octopulse archive --yes --reason "..."`. It writes a `paused` / `stale` marker without reading source or legacy status files.
- For non-trivial work, record only the tool and outcome: run `octopulse activity start --tool codex|claude|antigravity` after work begins, and `octopulse activity finish --tool ... --result updated|unchanged` before finishing. Never record prompts, source, tickets, or conversation text.
- For the current project, run `octopulse project report` after updating status. It may read Git metadata, recent commit subjects, the activity log, and an optional small `.ai/status.json`; it does not read source code or diffs.
- For all registered projects, including when the current directory is not a project, run `octopulse portfolio report --refresh auto --explain`. It refreshes changed project snapshots, then renders the portfolio report without agent synthesis.
- Codex v2 hooks may inject one session-start reminder and refresh reports after a turn only for a valid, registered, non-archived project. Hooks never read prompts, write `.otcopulse`, or record activity; semantic updates and non-trivial activity remain this skill's explicit responsibility.

Read [the schema reference](references/status-schema.md) only when creating or repairing a marker.
