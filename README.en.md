# OctoPulse

[繁體中文](README.md) · [English](README.en.md)

OctoPulse v2.0 is a lightweight project-progress system for AI-assisted development. Each tracked Git project keeps one small `.otcopulse` file, so an agent can recover reliable status without rereading source code, conversation history, or every project report.

![OctoPulse data flow](docs/octopulse-flow.svg)

## Design principles

- **Small, explicit pulse files.** `.otcopulse` is the sole status source. An empty file is uninitialized; a non-empty file must satisfy the strict JSON schema and remain under 4 KiB.
- **Context budget first.** A normal agent session reads only the Git root, lightweight Git facts, and the current project's marker. Reports are never injected into prompts automatically.
- **Scripted aggregation.** `octopulse report` only locates markers under registered roots and uses a fingerprint cache to avoid rewriting unchanged JSON, Markdown, or HTML.
- **Explicit, reversible writes.** Initialization, archiving, and agent-guidance injection require explicit commands. OctoPulse never reads, changes, or deletes `PROJECT_STATUS.md` or `.ai/status.json`.

## Install

Install the latest GitHub Release. In `auto` mode, the installer chooses one detected global-skill location in Codex, Claude Code, Antigravity priority order, preventing duplicate skills in shared loaders:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh
```

Install all three adapters only when the platforms do not share a skill loader:

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent all
```

The installer verifies the release archive SHA-256. Add `$OCTOPULSE_HOME/bin` to `PATH` as instructed, then verify the version:

```sh
octopulse --version
```

## Usage

### Track an active project

Run this from the project's Git root:

```sh
octopulse context
octopulse init --yes
```

`init` creates an empty `.otcopulse` and registers the Git root as trusted. At the end of non-trivial work, the agent updates the marker only when the goal, summary, next action, verification, or attention items materially changed, then validates it:

```sh
octopulse validate .otcopulse
```

To add a durable project reminder, explicitly select an adapter. Only this action updates `AGENTS.md` or `CLAUDE.md` with a minimal managed block:

```sh
octopulse init --yes --agent codex
```

### Archive an older project

Projects that are no longer maintained but should remain visible need no source-code or legacy-status read:

```sh
octopulse archive --yes --reason "Superseded by the new platform."
```

This writes a valid `phase: paused`, `health: stale` marker with an archive reason and explicit restart condition. Old projects that need no visibility should have neither a marker nor a registered scan root.

### Generate a cross-project report

```sh
octopulse report --format both --explain
```

The default output directory is `$OCTOPULSE_HOME/reports`; it contains `projects.json`, `latest.md`, and `index.html`. `--explain` lists marker reads, missing roots, and cache-hit reasons.

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
| `octopulse validate .otcopulse` | Validate marker schema and size. |
| `octopulse root add\|list\|remove PATH` | Manage trusted scan roots. |
| `octopulse report --format markdown\|html\|both --explain` | Generate or explain a cross-project report. |

## Documentation languages

This is the English companion to [README.md](README.md), the Traditional Chinese primary document. Keep feature, command, example, and flow changes synchronized in both README files within the same commit. CLI names, filenames, and schema fields remain English.
