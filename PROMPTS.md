# Prompts — routing templates + Messenger spec

Two audiences:
1. **You, the human router** — copy a template, fill placeholders, paste into
   the target worker session.
2. **The Messenger agent** (read-only) — reads workflow state, picks the right
   template by the decision table below, fills placeholders from git + files,
   and prints the ready-to-paste prompt. It never writes anything.

The agents themselves do NOT read this file — their READMEs route them.

---

## Placeholder glossary (how the Messenger fills each)

- `<NNNN-slug>` — task id + kebab slug, e.g. `0001-apifootball-events-projection`.
  Source: the single `[~]` row in `docs/ROADMAP.md`, cross-checked against the
  newest file in `specs/coordinator/tasks/`.
- `<sha>` — short commit SHA. **Always from `git log`, never from the LOG.md
  ref column** (those are hand-typed and drift). See per-template note for
  which commit.
- `<failed ACs>` — the `[FAIL]` line numbers in the verifier report's
  "Acceptance criteria" section, e.g. `AC3, AC5`.
- `<reason>` / `<date>` — left for the Coordinator to fill; Messenger leaves
  them as literal placeholders in escalation/amend prompts.

---

## State → next worker (Messenger decision table)

**`git log` is the source of truth, not `LOG.md`.** Every worker commits on
completion (their READMEs require it), so the most recent commit *is* the last
completed turn. Read `git log --oneline -8`, classify the newest task-bearing
commit by its subject, corroborate with the named file, then emit the matching
template. Use `LOG.md` only as a cross-check; if it disagrees with git, trust
git and note the discrepancy.

| Newest commit subject pattern | Corroborate | Next worker | Template |
|---|---|---|---|
| `<NNNN> … coordinator drafted task` (or `… open:`) | task file exists, ROADMAP `[~]` | Implementor | **T-IMPL** |
| `<NNNN> … coordinator opened followup` | follow-up task file exists | Implementor | **T-IMPL-FOLLOWUP** |
| `<NNNN> … coordinator amended` | task file has an `Amendment` line | Implementor | **T-IMPL-RESUME** |
| `<NNNN> … implement…` (touches `src/` or `tests/`) | the commit itself | Verifier | **T-VERIFY** |
| `<NNNN> … escalat…` | note in `specs/implementor/notes/` | Coordinator | **T-ESCALATION** |
| `<NNNN> … verifier report PASS` | report verdict = PASS | Coordinator | **T-COORD-PASS** |
| `<NNNN> … verifier report FAIL` | report verdict = FAIL | Coordinator | **T-COORD-FAIL** |

If the newest commit matches no pattern, the corroborating file is missing, or
git and `LOG.md` disagree on the task/action → **STOP, emit no prompt, report
the ambiguity.** A worker whose turn isn't committed is invisible — that's a
real finding, surface it ("last commit is the verifier report; no implementor
commit found for 0001 — did the Implementor forget to commit?").

---

## Templates

Every steady-state template ends with "Read specs/<role>/README.md first" so a
cold/cleared session self-routes. Keep that line.

### T-IMPL  (→ Implementor: fresh task)
```
Task <NNNN-slug> ready at specs/coordinator/tasks/<NNNN-slug>.md. Read
specs/implementor/README.md first. Your turn.
```

### T-IMPL-FOLLOWUP  (→ Implementor: follow-up after a FAIL)
```
Follow-up task <NNNN-followup-slug> ready at
specs/coordinator/tasks/<NNNN-followup-slug>.md. It scopes only the failed
item(s) from the <NNNN-original-slug> verifier report (<failed ACs>). Read
specs/implementor/README.md first. Your turn. Do not re-do work that
already passed.
```
Messenger: `<NNNN-original-slug>` = the most recent FAIL report; `<failed ACs>`
from that report's `[FAIL]` lines.

### T-IMPL-RESUME  (→ Implementor: resume after a Coordinator amendment)
```
Coordinator amended <NNNN-slug> (commit <sha>). Re-read
specs/coordinator/tasks/<NNNN-slug>.md — the Amendment line at the top is the
only change. Apply it, commit your already-staged work together with the fix,
run make lint && make test, append your LOG.md line, and tell me when ready
for the Verifier.
```
Messenger: `<sha>` = the commit that touched the task file with the amendment
(`git log --oneline -1 -- specs/coordinator/tasks/<NNNN-slug>.md`).

### T-VERIFY  (→ Verifier)
```
Implementor finished <NNNN-slug> at commit <sha>. Spec at
specs/coordinator/tasks/<NNNN-slug>.md. Read specs/verifier/README.md first.
Your turn.
```
Messenger: `<sha>` = the implementation commit
(`git log --oneline | grep -i "<NNNN>" | grep -iE "implement" | head -1`,
falling back to the newest commit touching `src/`/`tests/` for that task).

### T-COORD-PASS  (→ Coordinator)
```
Verifier returned PASS for <NNNN-slug> (commit <sha>, report at
specs/verifier/reports/<NNNN-slug>.md). Read specs/coordinator/README.md
first. Your turn.
```
Messenger: `<sha>` = the verifier report commit
(`git log --oneline -1 -- specs/verifier/reports/<NNNN-slug>.md`).

### T-COORD-FAIL  (→ Coordinator)
```
Verifier returned FAIL for <NNNN-slug> (commit <sha>, report at
specs/verifier/reports/<NNNN-slug>.md). Read specs/coordinator/README.md
first. Open the follow-up task scoping only the failed ACs.
```
Messenger: `<sha>` = the verifier report commit
(`git log --oneline -1 -- specs/verifier/reports/<NNNN-slug>.md`).

### T-ESCALATION  (→ Coordinator)
```
Implementor escalated <NNNN-slug>. Note at
specs/implementor/notes/<NNNN-slug>.md (commit <sha>). Working tree has
staged-but-uncommitted changes pending your decision. Read
specs/coordinator/README.md first.

Your turn:
1. Read the note.
2. Decide between (a) amend the task's §Files in place to authorize the
   needed change, or (b) open a precursor task, then resume <NNNN-slug>.
3. If amending: edit specs/coordinator/tasks/<NNNN-slug>.md to widen §Files;
   add "Amendment <date>: <reason>, see notes/<NNNN-slug>.md" near the top.
   Commit.
4. If precursor: open it; mark <NNNN-slug> paused in docs/ROADMAP.md.
5. Append your LOG.md line. Tell me the next handoff.
```
Messenger: `<sha>` = the note commit
(`git log --oneline -1 -- specs/implementor/notes/<NNNN-slug>.md`); leave
`<date>`/`<reason>` literal.

---

## Optional prepend: governing rules changed since the target last ran

Best-effort, Messenger may add this. If `CLAUDE.md`, `DECISIONS.md`, or any
`specs/*/README.md` was committed **after** the target role's previous LOG
entry, prepend:
```
Out-of-band changes since you last ran (commits <sha1>…):
- <one-line summary per changed governing file>
Re-read <files that changed>.
```
Detect via `git log --oneline <since>..HEAD -- CLAUDE.md DECISIONS.md
specs/*/README.md`. If unsure, skip it — a redundant re-read is cheap; a wrong
claim is not.

---

## Session hygiene (token budget)

- **Fresh session (or `/clear`) per fresh task, per agent.** Keep a session
  warm only across escalation/amendment/re-verify on the SAME task.
- **Route promptly.** Prompt cache expires after ~5 idle min.

---

## What NOT to put in a prompt
- Don't restate the agent's role, read order, or acceptance criteria — the
  READMEs and task spec carry those.
- Don't argue a decision. Open a "Revise D<n>" task instead.
The prompt is a router signal: "your turn, here's the pointer." Docs do the rest.

---

## The Messenger agent — standing prompt

Open a **fourth** session, paste the block below once. Thereafter just say
"next" (or paste a notification) and it prints the next handoff prompt. It is
**read-only** — it never edits, writes, or commits.

```
You are the Messenger for this repo's three-agent spec workflow
(coordinator → implementor → verifier). Your ONLY job each turn: read the
current workflow state and print the single ready-to-paste prompt for the
next worker. You are strictly READ-ONLY — never use Edit/Write, never
git commit/add/push, never run any state-changing command. Allowed: Read,
Grep, Glob, and read-only git (git log, git show --stat, git diff --stat).

Procedure every turn:
1. Run `git log --oneline -8`. The newest task-bearing commit is the last
   completed turn — git is the source of truth (every worker commits on
   completion). Identify the current task <NNNN-slug> and the acting role
   from the commit subject; cross-check against docs/ROADMAP's `[~]`/`[!]`
   row and LOG.md's last line. If git and LOG.md disagree, trust git and
   note it.
2. Corroborate against the named file (task spec / verifier report verdict /
   escalation note). If it's missing or unreadable, STOP and say what's
   ambiguous — do not guess.
3. Map the commit pattern to the next worker + template using the
   "State → next worker" decision table.
4. Fill placeholders per the glossary. ALWAYS get <sha> from `git log` using
   the per-template git command — never the LOG.md ref column.
5. Best-effort: if a governing doc (CLAUDE.md, DECISIONS.md, specs/*/README.md)
   was committed after the target role's previous turn, prepend the
   "governing rules changed" block. If unsure, skip it.
6. Output exactly: (a) one line — "Next: <ROLE> for <NNNN-slug> because
   <one-clause reason>", then (b) the filled prompt in a single fenced code
   block, nothing else. Do not act on the prompt.
```
