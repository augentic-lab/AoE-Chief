# Handing a task off to AoE Chief

AoE Chief supervises AI coding agents running in Agent of Empires. A delegated task gets its own git worktree, branch
and worker session; Chief runs the task's checks after every turn, sends failures back, queues the worker's questions
for the user, and has a second model review the result. The user only answers decisions and accepts the work.

Read this file when the user asks you to hand work off to Chief ("交给 chief", "delegate to chief", "hand this off").

## Adopt this conversation

When the user says “adopt this session” or “收编”, run `chief adopt` from your own shell with **no session argument**.
Chief resolves your current AoE tmux session and supervises this conversation in place, keeping its context and
current branch. Pass `--name`, `--goal` and repeated `--check` flags from the plan already agreed with the user:

```bash
chief adopt --name "Parser fix" --goal "Implement our agreed parser plan" \
  --check "python3 -m unittest discover -s tests"
```

Report the returned task ID and any needs-you note. If you are busy, Chief leaves the adoption notice pending;
the user runs `chief kickoff <id>` once you are at your input box. Adoption defaults to implementation, with
`--test-first` available when requested. It creates no isolated worktree or new worker. Use the hand-off steps
below only when the user wants a separate worker with a clean worktree.

## 1. Decide whether the plan is ready
Hand off only a plan the user has agreed to. If the goal, the scope or a key choice is still open, ask the user first
instead of guessing. One task per handoff; split unrelated work into separate handoffs.

## 2. Write the contract
Write a JSON file outside the repository (for example with `mktemp --suffix .json`):

```json
{
  "repo": "/absolute/path/to/the/repository",
  "name": "Short task name (becomes the branch chief/<id>)",
  "goal": "Self-contained description of the work (see below)",
  "checks": ["python3 -m pytest -q"],
  "protected": ["tests"],
  "test_first": true,
  "tool": "codex",
  "budget": {"rounds": 15, "hours": 4}
}
```

- **goal**: the worker has not seen this conversation. Write everything it needs: what to build and why, the
  decisions already made (and the alternatives rejected, so it does not reopen them), constraints, the files and
  functions involved, and what "done" means. If a longer plan exists in a file, give its absolute path as well.
- **checks**: shell commands, run in the worktree, that exit 0 only when the goal is met. Prefer the project's own
  test command. A check that always passes makes "done" meaningless.
- **protected**: paths the worker must not change, usually the existing test directories.
- **test_first**: keep `true` unless the user says otherwise. The worker first writes failing acceptance tests and the
  user approves them before implementation starts.
- **tool**: `codex` (default), `claude` or `antigravity`. Use the user's preference if they stated one.
- Optional: `scope` (the only directory the worker may change), `milestones` (list of text), `model`.

## 3. Create the task
Run Chief's `new` command with the contract. Use the Chief command named in your instructions; otherwise try `chief`,
then `python3 ~/aoe-chief/chief.py`:

```bash
chief new --from /tmp/contract.json --dry-run   # optional: preview the contract and kickoff prompt
chief new --from /tmp/contract.json
```

Do not implement the task yourself as well; the worker owns it from here.

## 4. Report back
Tell the user, briefly: the task id, the worker tool, the checks, and the protected paths. Remind them that the
acceptance tests will wait for approval in `chief inbox`, and that `chief watch` must be running for Chief to drive
the task. If the command printed "Needs you", pass that on.
