# `.octopulse` v3 schema

Write this file with `octopulse update`. Hand-edit it only when repairing an invalid marker, then run `octopulse validate .octopulse`.

The marker is either empty (uninitialized) or a UTF-8 JSON object no larger than 4 KiB.

```json
{
  "schema_version": 3,
  "name": "Example",
  "last_updated": "2026-07-11T10:00:00+08:00",
  "phase": "implementation",
  "health": "active",
  "goal": "Short current objective.",
  "summary": "Short factual status.",
  "next_action": "One concrete next step.",
  "verification": {
    "status": "partial",
    "last_command": "python -m unittest",
    "last_verified_at": "2026-07-11T10:00:00+08:00"
  },
  "attention": [],
  "handoff": {
    "tool": "codex",
    "created_at": "2026-07-11T10:00:00+08:00",
    "commit": "0123456789abcdef",
    "worktree_files": ["octopulse/core.py"],
    "read_first": ["octopulse/core.py"],
    "decisions": ["Keep the marker under 4 KiB."]
  }
}
```

Allowed `phase`: `planning`, `implementation`, `verification`, `maintenance`, `paused`.

Allowed `health`: `active`, `stable`, `needs_attention`, `blocked`, `stale`.

Allowed verification status: `passed`, `failed`, `not_run`, `partial`.

`handoff` is either `null` or the latest compact cross-model handoff. It never stores prompts, conversation text, diffs, or file contents. `worktree_files` is automatically captured from Git status; `read_first` names up to 8 existing project files the next agent should inspect before widening scope; `decisions` contains at most 4 short decision reasons.
