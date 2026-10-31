# Configuration

[Back to README](../README.md) · [Agents and transcripts](agents.md) · [Standing sessions](inbox.md#running-chief-in-aoe)

Config lives in `$AOE_CHIEF_HOME/config.json` (default `~/.local/state/aoe-chief/`).

| Key | Default | Meaning |
|---|---|---|
| `profile` | `main` | AoE profile |
| `lang` | `en` | Output language, `en` or `zh`. The `AOE_CHIEF_LANG` environment variable overrides it. Messages to workers are always in English |
| `engine` | `codex` | AI engine for briefs and decision drafts |
| `models` | see `chief engine` | Model and effort overrides, per engine and level |
| `check_timeout` | 300 | Seconds allowed per check command |
| `scope_ignore` | `[]` | Extra patterns the scope and cleanup cleanliness checks ignore |
| `decision_ai` | `false` | Let AI re-judge and draft new decisions |
| `stuck_after`, `max_auto_continues`, `rotate_at` | 3, 8, 70 | Automation limits |
| `presence_minutes` | 10 | Adopted tasks pause automatic messages while their latest human prompt is less than this many minutes old; `nudge` resumes immediately. Delegated tasks are unaffected |
| `review`, `review_engine`, `review_level` | `true`, the other engine (Codex for Antigravity), 2 | Cross review using Codex or Claude |
| `aoe_colors` | `true` | Mirror each task's state onto its AoE color dot: red needs you, amber working, green to accept |
| `commands` | `{}` | Launch a tool through your own command, e.g. `{"claude": "claude-proxy"}`. See below |

If another program called `aoe` comes earlier in your `PATH`, Chief prefers `~/.local/bin/aoe`. You can also set
`AOE_BIN`.

## Launching an agent through a wrapper

**Launching an agent through a wrapper.** Use `commands` when an agent must start through your own script rather
than its plain binary: an API proxy or model router, a pinned version, extra environment variables, a sandbox. The
command is used everywhere Chief starts that tool:

- `chief new` and session rotation pass it to `aoe add --cmd-override`. AoE stores it with the session, so restarts
  and resumes go through it too;
- Chief's own AI calls with that engine (Codex/Claude briefs, decision drafts, cross reviews).

A wrapper must:

1. pass every argument through. For Codex/Claude, these include AoE's `--session-id` / `--resume` and Chief's
   `-p` and `--model`;
2. `exec` the real binary, so AoE sees the agent's own process and screen;
3. keep the agent's transcript directory (`CLAUDE_CONFIG_DIR` / `CODEX_HOME`), or export the same value to Chief;
   for agy, keep the same home directory so Chief can read `~/.gemini/antigravity-cli`;
4. be on the `PATH` that tmux sessions see, or be given as an absolute path.

```bash
#!/usr/bin/env bash
# ~/.local/bin/claude-proxy: send Claude Code's API traffic through a local proxy
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
exec claude "$@"
```

Resume a conversation through the same wrapper that created it. A conversation that went through a proxy may contain
content the plain endpoint rejects.

`commands` applies only to sessions Chief starts. A session you open directly in AoE (its TUI, or `aoe add` without
`--cmd-override`) starts with AoE's own command for that tool, so it does not go through the wrapper. Mixing the two
is safe:

- each session keeps the command it was started with, including across restarts and resumes;
- Chief can track a session opened directly in AoE, because it reads the transcript, which does not depend on how
  the agent was launched;
- if Chief rotates a delegated session, the successor starts through Chief's command. Adopted sessions never rotate. Work carries over through the
  progress file as usual; only the endpoint changes (with a model router, for example, routed models become
  available).

To route sessions opened directly in AoE as well, configure the command in AoE itself (its
`session.agent_command_override` setting; see AoE's documentation). Chief's `commands` can then stay or be removed.

## State layout

```text
$AOE_CHIEF_HOME/
  config.json            settings and the sessions you track
  latest.md, reports/    the latest brief and the brief archive
  checks.json            check result cache
  preferences.md         your overrides of Chief's drafts; AI drafting reads this
  tasks/<id>/
    task.json            the contract and state
    decisions.json       the decision queue and its history
    events.jsonl         everything Chief did automatically
    review.md            the latest cross review card
    progress.md          progress copied before session/worktree cleanup
<worktree>/.chief/progress.md   the worker's handoff file (git-ignored locally)
```
