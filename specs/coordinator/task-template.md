# NNNN — <title>

**Roadmap item:** §X.Y — <copy the roadmap line>
**Depends on:** <task ids or "none">
**Status:** open

## Goal

One paragraph. What this task delivers and why now. Reference the relevant
`DECISIONS.md` IDs.

## In scope

Bullet list of concrete deliverables:
- File(s) created or modified, with paths (`src/<pkg>/<...>.py`, `tests/<...>.py`)
- Function / class signatures where relevant
- Tables / migrations / DDL
- Config keys added (and `.env.example` entry)

## Out of scope

Bullet list of things the implementor might be tempted to do, that they must
NOT do in this task. Each item should reference a future task or a decision.
Example:
- Parsing bronze into typed tables (Silver — out of scope)
- Touching the bronze write path (bronze is append-only)

## Files

Exhaustive list. Every file the implementor will touch:
- `src/<pkg>/<...>.py` — created
- `tests/<...>.py` — created
- `.env.example` — modified
- `docs/ROADMAP.md` — coordinator flips checkbox on close (NOT implementor)

If a file outside this list needs changing, the implementor must stop and
flag it back to the coordinator.

## Acceptance criteria (Definition of Done)

A numbered checklist of **testable** statements. The verifier runs these.
Example:
1. `make lint` passes with zero warnings.
2. `make test` passes; the suite includes a new test
   `tests/test_<x>.py::test_<y>` that asserts <z>.
3. A seeded bronze payload produces exactly the expected projected rows.
4. Bronze tables / write path are byte-identical (`git diff --stat`).

## Notes for the implementor

Anything non-obvious: bronze payload paths, the atomic-swap requirement, the
`docs/legacy/fix.py` reference for response shapes. Keep it short. If it's long,
you're making architectural choices the coordinator should make.

## Verifier checklist (mirror of DoD, plus housekeeping)

The verifier MUST confirm each acceptance criterion above PLUS:
- [ ] No files outside §Files were modified
- [ ] No new dependencies were added beyond those listed in §In scope
- [ ] No `DECISIONS.md` entries were violated
- [ ] `docs/ROADMAP.md` checkbox not flipped by implementor (coordinator owns it)
- [ ] Working tree clean on handoff; `LOG.md` line appended with a real SHA
