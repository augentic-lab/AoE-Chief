# Inbox and console

[Back to README](../README.md) · [Task guide](guide.md) · [Commands](commands.md)

### 📥 The inbox

```text
 AoE Chief · 1 needs you · 1 to confirm · 1 to accept · 4 tracked          last tick 2m ago · 14:05
 Delegated tasks
 [!] csv import            3f7b88ca  codex   idle      12m ago  protected files changed: tests/test_io.py
 [?] shop demo             f29dfc6f  codex   idle       3m ago  chief drafted decision shop-demo:1: A) plain text
 [+] parser fix            62f82720  claude  idle      40m ago  all checks pass (3/3), ready for you to accept
 Thinking sessions
 [ ] explore               9a1c03de  claude  running    0m ago
── shop demo ───────────────────────────────────────────────────────────────────────────────────────
 Decision shop-demo:1 (small, by rules)
 Q: Should receipt() return plain text lines or JSON? Recommendation: A) plain text
 Chief's draft: A) plain text
 ...
 N new task  a accept  r reply  d dismiss  n nudge  c close  o open  t tick  g refresh  q quit  ↑↓ move
```

#### Delegating from the inbox

Press `N` to delegate a task, even when the inbox is empty. The first editable line holds the task intent and the
second holds the repository path. Up/Down (`↑`/`↓`) switches the active line, marked with `>`, keeping both buffers.
The repository defaults to the selected item's source repository, or the current repository when none is available.
Subdirectories, symlinks and linked worktrees resolve to the original source repository.

On the intent line, `Tab` cycles a deterministic, deduplicated list of repositories from board tasks (including
unstarted tasks), tracked sessions and the current repository. On the repository line, `Tab` completes directory
paths: absolute, relative and `~/` paths are supported, with spaces and quotes kept literally. A unique directory
match gains a trailing slash; ambiguous matches extend to their longest common prefix. When the repository line
is empty, repeated `Tab` cycles the same known repositories. Typing or clearing the path returns to path completion.
Hidden names are included only when the name prefix being completed starts with `.`.

Repository edits validate live in the background. The composer shows a pending or invalid state, or the resolved
Git toplevel when valid. `Enter` from either line drafts a contract only with a nonblank intent and a valid
repository; the repository is checked again before drafting. If validation is pending, `Enter` shows a checking
message and keeps both lines editable. Once validation succeeds, press `Enter` again to draft.
Invalid input stays editable and creates no artifacts.
`Ctrl-U` clears the active line and Backspace edits it. Queued paste input is processed in batches, preserving
characters and order while keeping the UI responsive, without a redraw or Git validation for every character.

The contract appears in the detail pane. `Enter` creates and starts one task through the same lifecycle as
`chief new`; the default is to write and commit acceptance tests, then wait for your explicit approval before
implementation. Press `e` to edit the contract JSON in `$EDITOR` (default `vi`); the editor's arguments are supported.
Chief validates the result, restores the terminal and returns to the preview before starting anything. Invalid edits
or editor failures keep the last valid contract. `Esc` cancels input, a pending draft or a preview without creating a
task, branch, worktree or session; late draft results are discarded. PgUp/PgDn scroll long contracts.

In the contract preview, when idle, lowercase `t` toggles **Trust this folder** for this task only.
The default is **OFF** for each task; cancelling or reopening the composer resets it to OFF. The preview line
and footer show the current state. **ON** means Chief answers the agent's trust-this-folder prompt for you in
this repository, matching `chief new --trust`. **OFF** means you confirm it in the session, then run
`chief.py kickoff <id>`. Toggling creates nothing. Your selection survives contract editing, including invalid
edits and editor failures; AI-generated or edited contract JSON never sets it.

Drafting and startup run in the background, and repeated submissions are ignored. Failures appear in the inbox.
After confirming startup, let it finish; if startup fails, use the reported task ID to inspect or resume it with
`chief kickoff <task-id>` instead of submitting the same contract again.

For Codex startup interruptions, see [the update menu](agents.md#codex).

#### Adopting a tracked conversation

Select a tracked session without an active board task and press **A adopt**. Chief shows the inferred name, goal,
checks and protected paths. **Enter** adopts that session in place; **Esc** cancels without creating a task or
sending anything. It keeps the current branch and conversation context. Use `chief adopt` flags for a custom contract.
If the agent is busy, its needs-you note explains that the pending adoption notice will be sent automatically
when it is ready, or manually with `chief kickoff <id>`.

The task card says **adopted · in place**, and its close key becomes **c release**. Releasing leaves the session
running and never offers session/worktree cleanup. Previously tracked sessions return to Thinking sessions.
If you type directly into an adopted session, its card shows that automation is paused while you are active;
the pause expires automatically after `presence_minutes` (default 10), or you can use a nudge to resume immediately.

#### Task actions

The list separates **Delegated tasks** from tracked **Thinking sessions**, with urgent items first within each
group. Arrow keys or j/k move between items and skip headings; refreshes retain the selected session.

The footer shows only the keys that apply to the selected item: `a approve tests` / `a 批准测试` approves pending
tests, locks the listed files plus discovered support files, and starts build. `a approve paths` / `a 批准路径`
explicitly allows protected deliverables or their exact changed state; `a accept` / `a 采纳` accepts Chief's draft.
The detail pane explains these actions and that `r` sends feedback and keeps the
test phase, with a confirmation for consent-only replies as described in the [guide](guide.md#decisions-and-acceptance-tests). `r` replies to the pending
decision if there is one, otherwise straight to the session: guidance for a board task, your words unchanged for a
tracked session. `d` dismisses the decision, `n` sends the worker guidance, `b` sends the review issues back,
`c` closes the task as done, and `o` opens the session (inside tmux it switches to the agent's tmux session;
`prefix L` comes back). Sends run in the
background, so the inbox stays responsive. It refreshes every 15 seconds and never runs checks; `watch` does the
driving.

#### Asking the AI assistant

Press `?` to open a one-line **AI question box**, including on an empty board. Type a nonempty question and press
`Enter` to submit it to your configured engine/model. The detail pane shows **thinking** while generation runs in
the background; Up/Down navigation stays responsive. `Esc` dismisses an unsubmitted question or cancels active
generation, terminating its owned process and descendants and discarding late results. Recent questions and
answers remain available in the combined log described below; `?` opens a new question bar.

The **combined command and AI log** keeps the latest **20 submitted operations** in chronological submission
order in memory for this Inbox process. Each nonblank `:` command or `?` question creates one entry, updated
in place as it runs; the oldest entry is evicted at the limit. Entries retain command text, stdout/stderr,
errors, cancellation and actual exit status when available, or the question, answer, localized error,
cancellation and that answer's validated suggestions. The log survives refreshes and selection changes and
is not saved between launches. Unsubmitted or blank input does not create an entry.

A newly submitted operation shows its live result temporarily in the detail pane. Changing the selected item
dismisses that result and restores the item's details; background updates and refreshes never reopen dismissed
results. `Esc` also hides a completed result. Press uppercase `L` to open the combined log, even on an empty
board, initially at the newest entry at the bottom. `PgUp`/`PgDn` and `Space` scroll it; `Esc` leaves the log
without clearing it. Input, confirmations and active-operation cancellation keep precedence: during execution,
the first Esc cancels the owned operation, and another Esc leaves the log. Reading or scrolling the log and
pressing Enter there never submit an operation or send a reply.

The assistant is instructed to use your language, put the conclusion first and give at most three supporting points. It gets
explicit README and all `docs/*.md` documentation, the current board, pending decisions, recent events and review cards,
redacted with Chief's existing secret masker and enclosed as untrusted data. Generation uses `read_files=False`;
repository text and prior model answers cannot authorize actions or change Chief's rules. Command log contents
are never included in AI context.

When useful, an answer offers numbered **command suggestions**, checked against the existing command parser.
Press `1`–`9` to select a suggestion and **prefill** the `:` command bar. You can edit it or cancel with Esc;
in the combined log these digits refer to the latest AI answer, while older answers retain their own suggestions.
Only `Enter` submits the edited command, which is validated again. `close`, `clean`, `aoe session stop` and
`aoe session archive` retain their `y/N` confirmations. Asking, receiving an answer and selecting a suggestion
never execute commands, approve acceptance tests, resolve decisions or send replies. Unavailable engines,
timeouts, failed generation and unusable responses show localized errors; press `?` and submit again to retry.

After `c` successfully closes and archives a task, a second `(y/N)` confirmation offers to clean that task's
session and worktree. Enter, `n` or Esc keeps it archived. Accepting preserves progress, checks cleanliness
again and keeps the branch. A cleanup failure leaves the task closed and shows how to inspect or retry it.

#### Command bar

Press `:` for a one-line **command bar**, with a compact cheat sheet immediately above it. It accepts
`tasks`, `show`, `new`, `decide`, `nudge`, `close`, `clean`, `track`, `untrack` and `tick`, either bare or
with an optional `chief` prefix. Existing Chief CLI flags keep their meanings. It also accepts `aoe list`
(optionally `--json`) and `aoe session show|start|stop|archive|unarchive|restore <ID>` (`show` accepts
`--json`). The configured AoE profile and `AOE_BIN` resolution apply throughout.

```text
:tasks
:chief show csv-import --turns 5
:nudge csv-import "Keep quoted commas and Unicode intact"
:decide csv-import:2 --reply "Use the existing parser"
:new "Import CSV receipts" --repo '/home/me/project with spaces'
:aoe session restore <trashed-session-ID>
```

`Tab` completes supported command names and context-appropriate task/session IDs; `decide` completes
pending decision IDs. Archived sessions complete for `unarchive`, and trashed sessions for `restore`.
Completion reads a background cache, so input stays responsive; if data is still loading, try Tab again.
Up/Down recalls per-inbox command history and restores your unsubmitted draft. Ctrl-U clears the line;
Backspace edits it. `Enter` submits once and runs the command in the background. Stdout, stderr, errors
and exit status update the operation's log entry and its transient detail view; PgUp/PgDn scroll output.
After selection changes, use `L` to read retained output. `Esc` dismisses unsubmitted input or a confirmation.
During execution it terminates the owned command process and its descendants, discarding late results.
Already completed side effects are not undone.
After completion, Esc returns to the selected task's details without removing the log entry.

`close`, `clean`, `aoe session stop` and `aoe session archive` always require explicit `y/N` confirmation,
including when flags such as `--force` or `--dry-run` are present. Enter, `n` and Esc decline. A clean's
candidate list gets its own confirmation before any removal; cleanup safeguards and branch retention
still apply. A new intent's contract is reviewed inside the inbox: Enter approves, `e` edits, `n` aborts,
and Esc cancels. Explicit `new --yes` retains its normal CLI behavior.

The command bar is restricted: quoted arguments become literal argv values. Unquoted chaining,
pipelines, redirection, globbing, variable expansion and command substitution are rejected before launch;
arbitrary executables are unsupported. Quoted punctuation is literal data, never evaluated as shell code.
Registered task checks still run through the existing check mechanism.

#### Console layout

Use `chief console` for a tmux console: the inbox is on the **left** and an **interactive user shell**
is on the **right** by default. The shell prints the same cheat sheet first and starts in your home
directory (`~`); configure it with `chief console --shell-cwd ~/workspace`. The inbox retains its project
directory. The inbox supports narrow, half-width panes, including Unicode input, navigation, delegation,
command editing and scrolling. `chief console --layout top-bottom` places the inbox at the top and the
shell at the bottom; `--layout left-right` selects the default explicitly. `--every` sets the inbox's
refresh interval. Inside tmux, console splits the current window and runs the inbox in its original pane.
Outside tmux it creates a session, configures both panes, then attaches. Missing tmux and launcher errors
are reported on the CLI. The interactive shell supports your usual executables, pipelines and redirection;
the inbox command bar remains restricted. Use the tmux pane-switching keys to move between them.

#### Running Chief in AoE

To keep the inbox and the driver as standing sessions in AoE, register them as custom agents in
`~/.config/agent-of-empires/config.toml`. Point the custom agent named `chief` at `chief console` so
the AoE **chief inbox** session opens with the default split (use your actual absolute installation path):

```toml
[session]
custom_agents = { chief = "python3 /home/you/aoe-chief/chief.py console", chief-watch = "python3 /home/you/aoe-chief/chief.py watch --every 300" }
```

```bash
aoe add ~/aoe-chief -t "chief inbox" --tool chief --launch
aoe add ~/aoe-chief -t "chief watch" --tool chief-watch --launch
```

Then tasks keep moving without a terminal of yours open, and the AoE sidebar shows whether `watch` is alive.

#### Updating Chief

**Updating Chief:** pull your updates. A running `watch` compares chief.py's content hash against its loaded
startup hash before each tick. When it changes, watch logs one line and re-executes with the same Python
interpreter and original arguments. An ongoing pass finishes before the next iteration can reload; changes
to timestamps or other metadata alone do not trigger a reload.

The Inbox compares both `chief.py` and `chief_tui.py` with their loaded startup hashes on refresh. It shows
`Chief was updated; restart this inbox: aoe session stop/start <id>` in the header, substituting the Inbox's
session ID when available. Restart the Inbox manually with separate stop and start commands; it never
restarts itself. Do not use `aoe session restart` (it types a wake message that the Inbox would read as keys):

```bash
git -C ~/aoe-chief pull
aoe session stop <ID> && aoe session start <ID>   # Inbox session; watch reloads before its next tick
```

When upgrading standing sessions that predate source-update detection, stop/start both sessions once.

**Changing `custom_agents`:** AoE stores a session's command when the session is created, so editing
`config.toml` does not change existing sessions. Remove the old session (`aoe remove <ID>`) and run the matching
`aoe add` again. A trashed session still blocks the same title and path, so use a new title (for example
`chief console`) or empty the trash (`aoe session empty-trash` purges every trashed session and cannot be undone).
