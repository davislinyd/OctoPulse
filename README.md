# OctoPulse

OctoPulse v2.0 is a lightweight, marker-based progress hub for AI-assisted projects.
Each Git project that should be tracked owns one small `.otcopulse` file. Agents
read that marker and lightweight Git facts only; reports are rendered locally by
script, without reading project source code or conversation history.

## Install

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh
```

The installer adds detected Codex, Claude Code, and Antigravity global skills.
Use `--agent all` to install every adapter. It verifies the release archive
checksum before installing the runtime.

## Project lifecycle

For an active project, run from its Git root after approval:

```sh
octopulse init --yes
```

This creates an empty `.otcopulse` and registers the project root. At the end
of non-trivial work, the Agent writes a compact valid JSON pulse and runs:

```sh
octopulse validate .otcopulse
```

For a retired project that should stay visible without reading its source:

```sh
octopulse archive --yes --reason "Superseded by the new platform."
```

It writes a valid `paused` / `stale` marker and registers the project root. A
project without a marker or registered root is not reported.

## Status marker

`.otcopulse` is either empty (uninitialized) or a UTF-8 JSON object no larger
than 4 KiB. It contains only the current project state: name, timestamp, phase,
health, goal, summary, next action, verification, and attention items. See
[the schema](schemas/otcopulse.schema.json).

OctoPulse does not read, modify, or delete `PROJECT_STATUS.md` or
`.ai/status.json`. Those files remain entirely outside v2.

## Commands

```sh
octopulse context
octopulse init --yes [--agent codex|claude|antigravity|all]
octopulse archive --yes --reason "..."
octopulse validate .otcopulse
octopulse root add|list|remove PATH
octopulse report --format markdown|html|both --explain
```

The user-owned configuration, cache, and default reports live under
`$OCTOPULSE_HOME`, or `$XDG_CONFIG_HOME/octopulse` by default. Reports contain
`projects.json`, `latest.md`, and `index.html`; unchanged marker and Git facts
skip a rewrite.
