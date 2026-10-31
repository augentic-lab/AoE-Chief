# Command reference

[Back to README](../README.md) · [Task guide](guide.md) · [Configuration](configuration.md)

## Commands

| Area | Command | What it does |
|---|---|---|
| 👀 Observe | `sessions`, `track`, `untrack` | Pick AoE sessions to watch |
| | `inbox [--every SEC]` | Interactive terminal inbox: one key per action |
| | `brief [--ai] [--level 1-3]` | Triage report; with `--ai`, a model writes it from the facts |
| | `show <id> [--turns N]` | Drill into one task: progress file, checks, decisions, recent turns |
| | `task <id> --goal --check ...` | Attach a goal and checks to a session you did not create with `new` |
| | `check <id>` | Run a task's checks now |
| 🗂️ Tasks | `new`, `tasks`, `kickoff`, `close [--abandon] [--remove-session]` | Task lifecycle |
| | `adopt [session] [--dry-run]` | Supervise an existing conversation in place, preserving its context |
| | `clean [--dry-run] [--branches]` | Trash closed tasks' clean worktrees/sessions; keep branches by default |
| 🔁 Drive | `tick [--dry-run]`, `watch --every SEC` | One round, or a loop, of automatic actions |
| | `nudge <id> [TEXT] [--review]` | Send guidance or review issues back, and resume automation |
| | `rotate <id>`, `review <id>` | Start a fresh session now; run a cross review now |
| 📝 Decide | `decisions [--all] [--stats]` | The decision queue and acceptance stats |
| | `decide <id> --accept \| --reply TEXT \| --dismiss [REASON]` | Approve tests/support, protected additions or exact changed states, accept a draft, or send feedback; replies/dismissals grant no protected-path permission. `--redraft` / `--ai` never draft protected-path approvals |
| ⚙️ Settings | `engine [codex\|claude]`, `lang [en\|zh]` | AI engine and models per level; output language |

For `task <id>`, `--parked` suppresses inactivity reports and `--unpark` enables them again.
Omitting both flags preserves the task's parked state.

## Adopt an existing conversation

```text
chief adopt [session] [--name N] [--goal G] [--check CMD]... [--protected PATH]...
  [--scope S] [--test-first] [--rounds R] [--hours H]
  [--autonomy observe|suggest|auto] [--id TID] [--dry-run]
```

`session` accepts an AoE session ID or unique prefix, including a session already tracked without a board task.
When omitted, Chief resolves the current AoE tmux session (`aoe_<title>_<id8>`); `aoe_term_` shells are refused.
The session must be live, terminal-based, use Claude/Codex/Antigravity, have a Git project with at least one commit,
and have no active board owner. Invalid requests and `--dry-run` change nothing; dry-run prints the contract and notice.

Defaults: transcript title or AoE title for the name; goal “Carry out the plan agreed earlier in this conversation.”;
inferred checks and protected test directories; 15 rounds / 4 hours; `suggest` autonomy; no test-first gate unless
`--test-first` is given. Repeat `--check` and `--protected` to replace their inferred lists. Scope and protected
paths are repository-relative; checks run at the Git root. Existing dirty work is included in scope and review,
with existing protected changes recorded as exact state/path allowances. No new worktree, branch or session is created.

`chief kickoff <id>` resends the adoption notice when a busy/menu session becomes ready. `chief nudge` immediately
resumes supervision after human activity. `chief close` releases an adopted task without stopping, archiving or
messaging the session; `--abandon` releases it as abandoned. `--remove-session` and `rotate` are refused for adopted
tasks. `clean`, including `--branches`, excludes them completely.

## What tick does, situation by situation

For each active task, `tick` does at most one thing. It does nothing for tasks with `autonomy: observe`.

| Situation | Action |
|---|---|
| Any red signal, or a pending decision | Nothing; the task waits for you |
| Adopted task with a human prompt less than `presence_minutes` (10) minutes old | Pause automatic messages, including recovery and queued decision delivery; resume when the window expires |
| The turn was interrupted or errored | Recover once; if it fails again, hand it to you |
| Checks fail and the turn ended | Send the failing output back and ask the worker to continue |
| The same failure `stuck_after` (3) times in a row | Mark the task stuck and hand it to you |
| `max_auto_continues` (8) continues without your input | Pause and hand it to you |
| Context use ≥ `rotate_at` (70%) | Delegated tasks start a fresh session from `.chief/progress.md`; adopted tasks continue in the same conversation |
| All checks pass and HEAD has not been reviewed | The other model reviews the diff against the contract and writes `review.md` |

## Example brief

An illustrative brief:

```text
$ chief brief
# AoE brief  10-25 01:24

**L0:** tracking 3 · needs you 1 · to confirm 1 · to accept 1 · changed 0 · unchanged 0

## 🔴 Needs you
- **csv import** `5d1c09a2` codex · idle · 4m ago
  - decide csv-import:2: Should I delete the legacy importer? Options: A) delete B) keep. Recommendation: B
  - Handle: `chief.py decide csv-import:2 --reply "your decision"`

## 📝 To confirm (drafted by chief)
- **shop demo** `84392916` codex · idle · 0m ago
  - chief drafted decision shop-demo:1: A) Plain text lines, the function is documented as human-readable
  - Handle: `chief.py decide shop-demo:1 --accept` (or `--reply "..."`)

## ✅ To accept
- **parser fix** `a8e3f0c1` codex · idle · 2m ago
  - all checks pass (2/2), ready for you to accept
  - 🤖 chief: checks 1/2: sent the failures back and asked it to continue (#1)
  - Review (claude/sonnet): pass — Trailing commas are accepted in all three grammar rules; tests untouched.
  - Accept `chief.py close parser-fix` · send back `chief.py nudge parser-fix --review`
```
