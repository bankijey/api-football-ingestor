# Agent activity log

Append-only, one line per agent turn. Format:

```
YYYY-MM-DD HH:MM Berlin | <agent> | <task-id> | <action> | <result/ref>
```

Fields:
- `agent` — `coordinator` | `implementor` | `verifier`
- `task-id` — e.g. `0001-governance-adoption`
- `action` — short verb phrase (`drafted task`, `implemented`, `verified`)
- `result/ref` — commit hash, report path, or a short status

---
