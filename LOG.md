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

2026-07-05 13:26 Berlin | coordinator | 0001-apifootball-events-projection | drafted task | specs/coordinator/tasks/0001-apifootball-events-projection.md
2026-07-05 13:46 Berlin | implementor | 0001-apifootball-events-projection | escalated | specs/implementor/notes/0001-apifootball-events-projection.md — dirty tree (foreign seasons_override feature) blocks clean handoff + AC1 lint
2026-07-05 13:56 Berlin | coordinator | 0002-seasons-override-backfill | opened precursor | specs/coordinator/tasks/0002-seasons-override-backfill.md — precursor to land the foreign backfill feature + green baseline; 0001 paused
