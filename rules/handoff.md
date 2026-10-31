# Handing a task off to AoE Chief

AoE Chief supervises AI coding agents running in Agent of Empires. A delegated task gets its own git worktree, branch
and worker session; Chief runs the task's checks after every turn, sends failures back, queues the worker's questions
for the user, and has a second model review the result. The user only answers decisions and accepts the work.

Read this file when the user asks you to hand work off to Chief ("交给 chief", "delegate to chief", "hand this off")
or to adopt this conversation ("收编", "adopt this session").

## Adopt this conversation

When the user says “adopt this session” or “收编”, run `chief adopt` from your own shell with **no session argument**.
Chief resolves your current AoE tmux session and supervises this conversation in place, keeping its context and
current branch. Pass `--name`, `--goal` and repeated `--check` flags from the plan already agreed with the user:

```bash
chief adopt --name "Parser fix" --goal "Implement our agreed parser plan" \
  --check "python3 -m unittest discover -s tests"
```

Report the returned task ID and any needs-you note. If you are busy, Chief leaves the adoption notice pending;
the next tick sends it automatically once you are at your input box with no menu. The request that triggered
adoption does not activate the user-presence pause; new human prompts after adoption still do. The user may also
run `chief kickoff <id>` manually when ready. Adoption defaults to implementation, with
`--test-first` available when requested. It creates no isolated worktree or new worker. Use the hand-off steps
below only when the user wants a separate worker with a clean worktree.

## Research tasks

Hand research off with **"delegate to chief"**, rather than "adopt this session": only delegated tasks rotate
sessions, and reading many pages fills context quickly. Research uses an ordinary task contract and delivers
one `research/<id>/memo.md`; it needs no separate research contract format or claim database.

The goal states the question, the decision it serves, the stop condition, and rejected directions. Include
`read ~/aoe-chief/rules/research.md first`. Set `test_first` to `false` because the research plan has already
been agreed in conversation. The only check is the memo checker shown below.

Use `codex`, or `claude` only when its configured default model is a Claude model. GLM's web search returned
stale results in the pilot. Do not use `antigravity`: every shell fetch needs approval, blocking unattended
research. Chief uses the worker's configured default; do not add a `model` field to the contract.

Example ordinary task contract (replace the repository and research id):

```json
{
  "repo": "/absolute/path/to/the/repository",
  "name": "Research session recovery",
  "goal": "Read ~/aoe-chief/rules/research.md first. Question: how do agent CLIs resume sessions and compact context? Decision: should Chief session rotation use native resume? Stop condition: current official sources cover each supported CLI's resume and compaction behavior, limitations, and a recommendation with at most three reasons. Rejected directions: implementing rotation changes, surveying unrelated tools, and creating structured claim databases. Deliver research/session-recovery/memo.md, including queries tried and remaining uncertainty.",
  "checks": ["python3 ~/aoe-chief/tools/research_check.py research/session-recovery/memo.md"],
  "protected": ["tests"],
  "test_first": false,
  "tool": "codex",
  "budget": {"rounds": 15, "hours": 4}
}
```

Create it with `chief new --from <contract>` as below. Chief checks the memo, then its usual cross-model
review assesses the argument and omissions. Report the task id and check; this research flow skips test
approval. The user accepts the memo with `chief close` or sends feedback with `chief nudge`.

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
- Optional: `scope` (the only directory the worker may change), `milestones` (list of text). Do not set `model` or
  `effort`: Chief refuses them, because the worker always runs the default model from its own config.

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
