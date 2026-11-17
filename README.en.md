# OctoPulse

[繁體中文](README.md) · [English](README.en.md)

OctoPulse v3.1.0 is a lightweight project-progress system for AI-assisted development. Each tracked Git project keeps one small `.octopulse` file, so an agent can recover reliable status without rereading source code, conversation history, or every project report.

![OctoPulse data flow](docs/octopulse-flow.svg)

## Design principles

- **Small, explicit pulse files.** `.octopulse` is the sole status source. An empty file is uninitialized; a non-empty file must satisfy the strict JSON schema and remain under 4 KiB.
- **Context budget first.** A normal agent session reads only the Git root, lightweight Git facts, and the current project's marker. Reports are never injected into prompts automatically.
- **Model-neutral handoff.** A handoff stores only the latest tool, Git filenames, selected files, and short decisions; it never stores prompts, conversations, diffs, or file contents.
- **Scripted aggregation.** `octopulse portfolio report` only locates markers under registered roots, while the portfolio reads project snapshots. `auto` refreshes a project only when its marker, lightweight Git facts, legacy context, or activity fingerprint changed.
- **Explicit, reversible writes.** Initialization, archiving, and agent-guidance injection require explicit commands. OctoPulse never changes or deletes `PROJECT_STATUS.md` or `.ai/status.json`. Project reports may optionally read a small, allow-listed `.ai/status.json` as legacy context.

## Install

Install the latest GitHub Release. Antigravity and Grok Build share `~/.agents/skills`. Codex also receives `~/.codex/skills/octopulse`, and Claude Code receives `~/.claude/skills/octopulse`. In `auto` mode, the installer detects installed platforms. Choose one:

First install, or keep an existing skill:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh
```

Update an existing skill (replaces the `octopulse` skill):

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --force
```

Add `--agent all` to either command only when every platform is required. Antigravity and Grok Build share `~/.agents/skills/octopulse`, and Codex uses `~/.codex/skills/octopulse`:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent all
```

The installer verifies the release archive SHA-256 and attempts to create `~/.local/bin/octopulse`; that directory is commonly already on `PATH`. If another command already occupies that path, the installer leaves it untouched and prints the `$OCTOPULSE_HOME/bin` PATH fallback. Then verify the version:

```sh
octopulse --version
```

Install Grok Build explicitly to add the shared skill and its native Stop hook; no second `~/.grok/skills` copy is created:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok
grok inspect
```

`grok inspect` should show `~/.agents/skills/octopulse` and `~/.grok/hooks/octopulse.json`. grok.com web Skills cannot directly run the local `octopulse` CLI and are outside this integration's scope.

In Grok Build, read progress and write it back when the semantic status changes:

```sh
octopulse status
octopulse update --tool grok --summary "..." --next "..."
```

`update` validates the marker, records one finish event, and refreshes the project report. `activity start|finish` remain available on their own.

## Usage

### Upgrade from v2

v3 recognizes only `.octopulse`. After updating the CLI, run this once from the Git root of every project that still has a v2 `.otcopulse` marker:

```sh
octopulse migrate-marker --yes
```

The command atomically renames the marker in place without reading or rewriting its contents, source code, Git history, or legacy status. It refuses a two-marker conflict and safely reports when the new marker already exists or neither marker exists. The installer never migrates projects automatically.

### Upgrade from marker schema v2

The current CLI reports a valid schema v2 marker as `migration_required`. It remains readable for reports, but cannot create handoffs. Update the OctoPulse CLI and skill in every development environment first, then explicitly run this in every project that needs handoff:

```sh
octopulse migrate-schema --yes
```

The command only upgrades the marker to schema v3 and adds `"handoff": null`; it never reads source code, conversations, or Git history.

### Track an active project

Read the current progress from the project's Git root:

```sh
octopulse status
```

Write the first semantic pulse:

```sh
octopulse update --yes --goal "Ship the current milestone." --next "Open the pull request."
```

`update --yes` creates a valid `.octopulse`, registers the Git root, and validates before writing. When the marker is schema v2, the same command upgrades it to v3, keeps the existing fields, and registers the root. Every successful write refreshes the project report and the portfolio report. Later commands send only the fields that changed:

```sh
octopulse update --summary "The current work is verified locally." --next "Open the pull request."
```

Tell an agent “put this project's progress into OctoPulse” and it enrolls the project in that same turn, without a second confirmation. The reports are then available at `.octopulse-reports/index.html` in the project and `~/.config/octopulse/reports/index.html` for every registered project. After that, the Codex, Claude Code, and Grok Stop hooks refresh those reports on later turns in the enrolled project.

`init --yes` can still create an empty marker. To add a durable project reminder, select an adapter. Only that action updates `AGENTS.md` or `CLAUDE.md`:

```sh
octopulse init --yes --agent codex
```

### Scenario: an AI agent reads the skill

After installing the global skill, tell an agent: “Use the OctoPulse skill to read the current project status. If this task changes the goal, summary, next action, verification, or attention, write it back with update.” The agent first runs:

```sh
octopulse status
```

A `valid` result is the progress. Read the handoff only when switching models:

```sh
octopulse handoff show
```

`handoff show` prints a resume packet bounded by the marker limit. The receiving model reads only `read_first` files and necessary Git changes; it must not scan the project merely to restore context, and expands scope only when that information is insufficient. When the work changes semantic status:

```sh
octopulse update --tool codex --summary "The marker write path is verified." --next "Commit the pulse with the work."
```

That `update` validates the marker, records one finish event, and refreshes the project report. Run `octopulse handoff create` before switching models. `activity start|finish` and a separate `validate` remain available, but they are not the default closing steps.

For a cross-device switch, commit and push `.octopulse` with the code changes. `handoff show` warns when the marker is uncommitted, because that handoff is local-only. Each platform keeps its own full conversations; OctoPulse never copies or synchronizes them.

When the user does not explicitly ask to change progress, the agent only views reports: `octopulse status` for the current project and `octopulse portfolio report --refresh auto --explain` for every managed project. It does not ask for a goal or next action, and it does not write a marker. When the request asks to put project progress into OctoPulse, the agent enrolls it in the same turn with `octopulse update --yes --tool <current tool>`. It passes `--goal`, `--summary`, or `--next` only when the user stated them; omitted goal and next use the CLI placeholders. The same command upgrades schema v2. Repairing an `invalid` marker always requires approval. For a cross-project view, the skill runs `octopulse portfolio report --refresh auto --explain` from any directory.

### Scenario: direct human or automation commands

Without AI, run this from the project's Git root:

```sh
octopulse status
octopulse update --summary "..." --next "..."
octopulse project report --lang en
```

Add `--tool` to `update` when the tool activity should be recorded too. Omit `--tool` when no AI was used.

Generate a portfolio from any directory, or select a CI output directory:

```sh
octopulse portfolio report --refresh auto --output ./octopulse-portfolio
```

### Archive an older project

Projects that are no longer maintained but should remain visible need no source-code or legacy-status read:

```sh
octopulse archive --yes --reason "Superseded by the new platform."
```

This writes a valid `phase: paused`, `health: stale` marker with an archive reason and explicit restart condition. Old projects that need no visibility should have neither a marker nor a registered scan root.

### Project reports and AI tool activity

After an AI tool creates a commit, record the tool and conversation locally. Do not put them in the commit message:

```sh
octopulse session record --commit HEAD --tool claude --session "$SESSION_ID"
```

The report shows the tool beside that commit. When a session id exists, Open conversation uses `octopulse://resume?commit=<sha>` to resume it on this computer. The record is `.ai/octopulse-sessions.jsonl` and is not pushed.

`octopulse update --tool codex` records one finish event and refreshes the current repo's report and the portfolio report. A successful marker write refreshes both as well. The same pieces can be run separately:

```sh
octopulse activity finish --tool codex --result updated
octopulse project report
```

Artifacts live in `.octopulse-reports/`: `snapshot.json`, `latest.md`, `index.html`, and a minimal `activity.jsonl`. The project report reads only the marker, Git metadata, the latest 10 commit subjects, activity events, and an optional small `.ai/status.json`; it never reads source code or diffs. `.octopulse` remains the sole semantic status source; legacy status is read-only context.

When the installer detects Codex, it automatically migrates known v1 `UserPromptSubmit` hooks to two global v3 hooks: `SessionStart` injects one short skill reminder at `startup|resume`; `Stop` refreshes changed reports only for valid, registered, non-archived projects. They read `hook_event_name` and `cwd`. They do not read prompts, source code, diffs, or conversations, and never write `.octopulse` or activity. Disable or remove them during reinstall with:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --without-codex-hooks
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --remove-codex-hooks
```

The installer automatically migrates only known v1 handlers in `~/.codex/hooks.json` and preserves other hooks. Disable legacy hooks from `config.toml`, plugins, or other sources with Codex `/hooks`, because hooks from multiple sources all run.

Claude Code gets the same behavior merged into the existing `~/.claude/settings.json`, leaving the file's other settings and hooks in place. The `SessionStart` matcher is `startup|resume|clear|compact|fork`, and stdout uses the `hookSpecificOutput.additionalContext` field Claude reads. `Stop` only refreshes reports and does not return `additionalContext`, which would keep the turn open. Disable or remove them with:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent claude --without-claude-hooks
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent claude --remove-claude-hooks
```

Grok Build uses a separate `~/.grok/hooks/octopulse.json` containing only a `Stop` hook. Current stdin carries both `hook_event_name: "Stop"` and `hookEventName: "stop"`; the handler accepts either and uses only `cwd`. It incrementally refreshes reports only for valid, registered, non-archived projects, never reads prompts, source code, diffs, or conversations, and never writes a marker or activity. Grok does not deliver `SessionStart` stdout to the model, so no SessionStart hook is installed, and `Stop` does not return `additionalContext` that would continue the turn. Disable or remove it with:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok --without-grok-hooks
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok --remove-grok-hooks
```

### Portfolio report

```sh
octopulse portfolio report --refresh auto --explain
```

This command works from any directory. It refreshes only project snapshots whose fingerprints changed, then renders `$OCTOPULSE_HOME/reports/projects.json`, `latest.md`, and `index.html`. The HTML switches between overview and project detail views, with Chinese/English UI through a URL language parameter; human-written goals and summaries remain in their original language.

## `.octopulse` format

A marker is either empty or UTF-8 JSON under 4 KiB. See the complete [schema](schemas/octopulse.schema.json).

```json
{
  "schema_version": 3,
  "name": "Example Project",
  "last_updated": "2026-07-12T10:00:00+08:00",
  "phase": "implementation",
  "health": "active",
  "goal": "Ship the current milestone.",
  "summary": "The current work is verified locally.",
  "next_action": "Open the pull request.",
  "verification": {
    "status": "passed",
    "last_command": "python3 -m unittest",
    "last_verified_at": "2026-07-12T10:00:00+08:00"
  },
  "attention": [],
  "handoff": {
    "tool": "codex",
    "created_at": "2026-07-12T10:00:00+08:00",
    "commit": "0123456789abcdef",
    "worktree_files": ["octopulse/core.py"],
    "read_first": ["octopulse/core.py"],
    "decisions": ["Keep the marker under 4 KiB."]
  }
}
```

## Command reference

| Command | Purpose |
| --- | --- |
| `octopulse` / `octopulse status` | Print the current project pulse. `--json` is for agents; `--lang en` prints English. |
| `octopulse update` | Create or patch the marker. A missing or empty marker needs only `--yes`; omitted goal and next use placeholders. `--yes` also upgrades schema v2 to v3 and refreshes both reports. |
| `octopulse context` | Read-only inspection of the current Git project and marker. |
| `octopulse init --yes` | Create an empty marker and register its root. |
| `octopulse migrate-marker --yes` | Atomically rename a v2 `.otcopulse` marker to `.octopulse` in the same Git root. |
| `octopulse migrate-schema --yes` | Explicitly upgrade one valid schema v2 marker to v3. |
| `octopulse handoff create\|show` | Write the latest handoff, or read the token-bounded resume packet. |
| `octopulse archive --yes --reason TEXT` | Archive a project as `paused` / `stale`. |
| `octopulse activity start\|finish --tool TOOL` | Record non-trivial AI tool activity without prompts. |
| `octopulse hook codex-session-start\|codex-stop` | Used by Codex lifecycle hooks; never use it to infer project status manually. |
| `octopulse hook claude-session-start\|claude-stop` | Used by Claude Code lifecycle hooks; never use it to infer project status manually. |
| `octopulse hook grok-stop` | Used by the Grok Build Stop hook; never use it to infer project status manually. |
| `octopulse project report` | Generate the current repo's snapshot, Markdown, and HTML. |
| `octopulse portfolio report --refresh auto` | Generate a portfolio report from any directory. |
| `octopulse validate .octopulse` | Validate marker schema and size. |
| `octopulse root add\|list\|remove PATH` | Manage trusted scan roots. |
| `octopulse report` | Compatibility alias for `portfolio report`. |

## Documentation languages

This is the English companion to [README.md](README.md), the Traditional Chinese primary document. Keep feature, command, example, and flow changes synchronized in both README files within the same commit. CLI names, filenames, and schema fields remain English.
