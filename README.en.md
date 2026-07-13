# OctoPulse

[繁體中文](README.md) · [English](README.en.md)

OctoPulse v2.2.0 is a lightweight project-progress system for AI-assisted development. Each tracked Git project keeps one small `.otcopulse` file, so an agent can recover reliable status without rereading source code, conversation history, or every project report.

![OctoPulse data flow](docs/octopulse-flow.svg)

## Design principles

- **Small, explicit pulse files.** `.otcopulse` is the sole status source. An empty file is uninitialized; a non-empty file must satisfy the strict JSON schema and remain under 4 KiB.
- **Context budget first.** A normal agent session reads only the Git root, lightweight Git facts, and the current project's marker. Reports are never injected into prompts automatically.
- **Scripted aggregation.** `octopulse portfolio report` only locates markers under registered roots, while the portfolio reads project snapshots. `auto` refreshes a project only when its marker, lightweight Git facts, legacy context, or activity fingerprint changed.
- **Explicit, reversible writes.** Initialization, archiving, and agent-guidance injection require explicit commands. OctoPulse never changes or deletes `PROJECT_STATUS.md` or `.ai/status.json`. Project reports may optionally read a small, allow-listed `.ai/status.json` as legacy context.

## Install

Install the latest GitHub Release. Codex, Antigravity, and Grok Build share `~/.agents/skills`; in `auto` mode, the installer detects installed platforms but installs one shared global skill, preventing duplicate skills in a shared loader. Choose one:

First install, or keep an existing skill:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh
```

Update an existing skill (replaces the `octopulse` skill):

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --force
```

Add `--agent all` to either command only when every platform is required; Codex, Antigravity, and Grok Build still share one `~/.agents/skills/octopulse` copy:

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

For non-trivial Grok Build work, the skill explicitly records minimal activity events:

```sh
octopulse activity start --tool grok
octopulse activity finish --tool grok --result updated
```

## Usage

### Track an active project

Run this from the project's Git root:

```sh
octopulse init --yes
```

`init` creates an empty `.otcopulse` and registers the Git root as trusted. A human who has already decided to initialize does not need `context` first; it is the AI skill's read-only diagnostic step. At the end of non-trivial work, the agent updates the marker only when the goal, summary, next action, verification, or attention items materially changed, then validates it:

```sh
octopulse validate .otcopulse
```

To add a durable project reminder, explicitly select an adapter. Only this action updates `AGENTS.md` or `CLAUDE.md` with a minimal managed block:

```sh
octopulse init --yes --agent codex
```

### Scenario: an AI agent reads the skill

After installing the global skill, tell an agent in a tracked project: “Use the OctoPulse skill to get the current project status, then update the pulse and project report after this non-trivial task.” Codex, Claude Code, Antigravity, or Grok Build first runs:

```sh
octopulse context
```

For a `valid` result, the skill reads only `.otcopulse` and lightweight Git facts. It records tool-only events at the start and end of the work:

```sh
octopulse activity start --tool codex
# The agent completes the work and updates .otcopulse only if semantic status changed.
octopulse validate .otcopulse
octopulse activity finish --tool codex --result updated
octopulse project report
```

`context` and the following commands run consecutively in the same agent turn, not as two conversations. When the request explicitly says to initialize OctoPulse and the state is `missing`, the agent may run `context` and then `octopulse init --yes` in that turn. `uninitialized` means an empty marker already exists and is not recreated; the agent waits for a stated goal or clear facts from later non-trivial work before creating semantic status. It asks whether to create a marker only when the request is merely to inspect status and the state is `missing`; repairing an `invalid` marker always requires approval. It never scans source code to infer progress. For a cross-project view, explicitly ask it to “use the OctoPulse skill to generate the portfolio report.” The skill can run `octopulse portfolio report --refresh auto --explain` from any directory.

### Scenario: direct human or automation commands

The same workflow works in a shell or CI script without AI. After initialization, maintain `.otcopulse` with an editor; write and validate it only when status materially changes:

```sh
octopulse init --yes
# Update .otcopulse with an editor: goal, summary, next_action, verification, or attention.
octopulse validate .otcopulse
octopulse project report --lang en
```

When an AI tool was used for a non-trivial task, explicitly bracket the task with activity events. Omit these commands when no AI was used:

```sh
octopulse activity start --tool claude
# Develop, test, or review.
octopulse activity finish --tool claude --result unchanged
```

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

Create a separate, locally ignored project snapshot and report in the current repo:

```sh
octopulse activity start --tool codex
# After non-trivial work finishes
octopulse activity finish --tool codex --result updated
octopulse project report
```

Artifacts live in `.octopulse-reports/`: `snapshot.json`, `latest.md`, `index.html`, and a minimal `activity.jsonl`. The project report reads only the marker, Git metadata, the latest 10 commit subjects, activity events, and an optional small `.ai/status.json`; it never reads source code or diffs. `.otcopulse` remains the sole semantic status source; legacy status is read-only context.

When the installer detects Codex, it automatically migrates known v1 `UserPromptSubmit` hooks to two global v2 hooks: `SessionStart` injects one short skill reminder at `startup|resume`; `Stop` refreshes changed reports only for valid, registered, non-archived projects. They do not read prompts, source code, diffs, or conversations, and never write `.otcopulse` or activity. Disable or remove them during reinstall with:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --without-codex-hooks
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --remove-codex-hooks
```

The installer automatically migrates only known v1 handlers in `~/.codex/hooks.json` and preserves other hooks. Disable legacy hooks from `config.toml`, plugins, or other sources with Codex `/hooks`, because hooks from multiple sources all run.

Grok Build uses a separate `~/.grok/hooks/octopulse.json` containing only a `Stop` hook. It uses only the hook event name and `cwd`; it incrementally refreshes reports only for valid, registered, non-archived projects, never reads prompts, source code, diffs, or conversations, and never writes a marker or activity. Grok's passive hook stdout cannot inject model context, so no SessionStart hook is installed. Disable or remove it with:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok --without-grok-hooks
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok --remove-grok-hooks
```

### Portfolio report

```sh
octopulse portfolio report --refresh auto --explain
```

This command works from any directory. It refreshes only project snapshots whose fingerprints changed, then renders `$OCTOPULSE_HOME/reports/projects.json`, `latest.md`, and `index.html`. The HTML switches between overview and project detail views, with Chinese/English UI through a URL language parameter; human-written goals and summaries remain in their original language.

## `.otcopulse` format

A marker is either empty or UTF-8 JSON under 4 KiB. See the complete [schema](schemas/otcopulse.schema.json).

```json
{
  "schema_version": 2,
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
  "attention": []
}
```

## Command reference

| Command | Purpose |
| --- | --- |
| `octopulse context` | Read-only inspection of the current Git project and marker. |
| `octopulse init --yes` | Create an empty marker and register its root. |
| `octopulse archive --yes --reason TEXT` | Archive a project as `paused` / `stale`. |
| `octopulse activity start\|finish --tool TOOL` | Record non-trivial AI tool activity without prompts. |
| `octopulse hook codex-session-start\|codex-stop` | Used by Codex lifecycle hooks; never use it to infer project status manually. |
| `octopulse hook grok-stop` | Used by the Grok Build Stop hook; never use it to infer project status manually. |
| `octopulse project report` | Generate the current repo's snapshot, Markdown, and HTML. |
| `octopulse portfolio report --refresh auto` | Generate a portfolio report from any directory. |
| `octopulse validate .otcopulse` | Validate marker schema and size. |
| `octopulse root add\|list\|remove PATH` | Manage trusted scan roots. |
| `octopulse report` | Compatibility alias for `portfolio report`. |

## Documentation languages

This is the English companion to [README.md](README.md), the Traditional Chinese primary document. Keep feature, command, example, and flow changes synchronized in both README files within the same commit. CLI names, filenames, and schema fields remain English.
