# `.octopulse` v2 schema

The marker is either empty (uninitialized) or a UTF-8 JSON object no larger than 4 KiB.

```json
{
  "schema_version": 2,
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
  "attention": []
}
```

Allowed `phase`: `planning`, `implementation`, `verification`, `maintenance`, `paused`.

Allowed `health`: `active`, `stable`, `needs_attention`, `blocked`, `stale`.

Allowed verification status: `passed`, `failed`, `not_run`, `partial`.
