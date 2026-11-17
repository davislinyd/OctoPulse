---
name: OctoPulse
description: Use for OctoPulse project status, per-project reports, AI tool activity, and portfolio reports across registered projects.
---

# OctoPulse

When the user does not explicitly ask to enroll a project or to change its goal, summary, next action, verification, or attention, only view reports. Run `octopulse status` in the current Git project and `octopulse portfolio report --refresh auto --explain` for every registered project. Show those results. Do not ask for a goal or next action, and do not write a marker.

When the user explicitly asks to put a project into OctoPulse, enroll it in the same turn. Do not ask for a goal or next action. Run `octopulse status`, then:

- `missing` or `uninitialized`: run `octopulse update --yes --tool codex|claude|antigravity|grok`. Pass `--goal`, `--summary`, or `--next` only when the user stated that fact. Omitted goal and next use the CLI placeholders. Do not scan the repository to invent them. Use the tool that is running this session.
- `migration_required`: run `octopulse update --yes` with the same `--tool`. This upgrades schema v2 to v3, keeps the existing fields, registers the Git root, and refreshes both reports. Add `--goal`, `--summary`, or `--next` only when the user stated a change.
- A legacy `.otcopulse` filename is not the current marker. When the user asked to enroll the project, run `octopulse migrate-marker --yes`, then continue with the resulting state.
- `valid`: run `octopulse update --tool <current tool>` only for fields the user explicitly changed.
- `invalid`: explain the errors and stop. Repair requires separate approval.

Use `octopulse status --json` when a machine-readable pulse is needed. It reads only the Git root, `.octopulse`, and lightweight Git facts.

After enrollment, tell the user both report paths: `<repo>/.octopulse-reports/index.html` for this project, and `~/.config/octopulse/reports/index.html` for every registered project. The write refreshes both immediately. Later turns in that project are picked up by the installed Codex, Claude Code, and Grok Stop hooks, which refresh changed reports for a valid, registered, non-archived project. Codex and Claude Code also inject one short `octopulse status` reminder at session start. The Stop hook also updates a local journal from new commits, the marker's next action, and structured transcript fields (todo items, counts, edited paths, whether `git commit` ran). Hooks never store prompts or replies, write `.octopulse`, or record activity. Grok's SessionStart stdout is not delivered to the model, so Grok only installs the Stop hook.

- When taking over from another model, run `octopulse handoff show`, then read only its `read_first` files and necessary Git changes before expanding scope. Before switching tools, run `octopulse handoff create --tool codex|claude|antigravity|grok`.
- When the user asks what was done or what remains, run `octopulse log --limit 10` or `octopulse todo` instead of reading history or transcripts. Do not run them by default.
- The Claude Code and Codex Stop hooks link commits you make to this session automatically. Only when the report shows the commit as unrecorded, run `octopulse session record --commit HEAD --tool claude|codex|grok --session <session-id>`. Omit `--session` when the id is not available. Do not put the tool or session id in the commit message. Do not record a commit you did not make.
- For a retired project that should remain visible, ask approval and run `octopulse archive --yes --reason "..."`. It writes a `paused` / `stale` marker without reading source or legacy status files.
- `octopulse activity start|finish` and `octopulse validate .octopulse` remain available. `update` already validates, so they are not part of the default loop. Never record prompts, source, tickets, or conversation text. Commit and push `.octopulse` with the work before cross-device handoff.
- For all registered projects, including when the current directory is not a project, run `octopulse portfolio report --refresh auto --explain`.

Read [the schema reference](references/status-schema.md) only when repairing an invalid marker by hand.
