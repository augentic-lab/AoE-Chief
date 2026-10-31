<p align="center">
  <img src="docs/assets/banner.svg" alt="AoE Chief: a standby chief of staff for your parallel AI coding agents" width="820">
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Python 3.7+" src="https://img.shields.io/badge/python-3.7%2B-3776AB?logo=python&logoColor=white">
  <img alt="Dependencies: none" src="https://img.shields.io/badge/dependencies-none-brightgreen">
  <a href="https://github.com/agent-of-empires/agent-of-empires"><img alt="Built on Agent of Empires" src="https://img.shields.io/badge/built%20on-Agent%20of%20Empires-8957e5"></a>
  <a href="https://github.com/openai/codex"><img alt="Works with Codex CLI" src="https://img.shields.io/badge/works%20with-Codex%20CLI-black"></a>
  <a href="https://github.com/anthropics/claude-code"><img alt="Works with Claude Code" src="https://img.shields.io/badge/works%20with-Claude%20Code-d97757"></a>
</p>

<p align="center">
  <a href="#-quick-start">Quick start</a> ·
  <a href="#-how-it-works">How it works</a> ·
  <a href="docs/commands.md">Commands</a> ·
  <a href="docs/architecture.md">Architecture</a> ·
  <a href="rules/communication.md">Agent rules</a>
</p>

---

> **You define the task. You accept the result. Chief handles everything in between.**

You run five AI coding agents at once. One is stuck, one is waiting for an answer, one says it is "done" but its
tests fail, and two are fine. You cannot tell which is which without checking every session.

## What Chief does

**AoE Chief** keeps watch over your [Agent of Empires](https://github.com/agent-of-empires/agent-of-empires)
sessions:

- It drives delegated tasks to completion: it runs the checks, nudges the agent forward, and reviews the result
  with a second model.
- It only interrupts you when a human decision is really needed.
- Its reports are **thin first, thick on demand**: one line per thing that matters, details when you ask.

The inbox during the demo below, captured from a real run. Chief has drafted an answer to the worker's question,
and `a` sends it:

<p align="center">
  <img src="docs/assets/inbox.svg" alt="AoE Chief inbox: the demo task waits on a decision that Chief has drafted" width="820">
</p>

<details>
<summary>Why Chief?</summary>

| The problem | What Chief does about it |
|---|---|
| 🧠 **One human, many agents.** Context switching between parallel sessions does not scale. | Watches every session and tells you only what changed and what needs you. |
| 🗣️ **Replies that are complete but not useful.** Agents dump everything and bury the conclusion. | A shared [communication protocol](rules/communication.md) makes agents lead with the conclusion and end each turn with a machine-readable closing block. |
| 🏁 **"Done" that is not done.** An idle process or a confident agent proves nothing. | A task is done when its **executable checks** pass and **another model** has reviewed the diff. |
| 🔁 **You are the "continue" button.** Every small nudge and decision waits for you. | Chief continues automatically on failing checks, drafts small decisions for one-command approval, and escalates only big ones. |

</details>

## 🧭 How it works

Define a task with a goal and executable checks. Chief creates a worktree and worker session,
runs the checks after each turn, and sends failures back to the worker. Once checks pass, another
model reviews the result. You approve decisions and accept the finished work.

See the [task guide](docs/guide.md) for the workflow and [architecture](docs/architecture.md) for the design.

## 🚀 Quick start

**Requirements:**

- Linux or macOS, Python 3.7+ (standard library only), git
- [Agent of Empires](https://github.com/agent-of-empires/agent-of-empires) (`aoe`, tested with 1.21)
- A worker: [Codex CLI](https://github.com/openai/codex), [Claude Code](https://github.com/anthropics/claude-code),
  or Antigravity CLI (`agy`, transcript format based on a 1.4.11 probe).
  Chief's AI briefs, decision drafts, and reviews use Codex or Claude. Install both for mutual Codex/Claude review;
  Antigravity work uses Codex by default, or Claude when configured with `review_engine`.

```bash
git clone https://github.com/augentic-lab/AoE-Chief.git ~/aoe-chief
alias chief="python3 ~/aoe-chief/chief.py"
chief init

# Teach your agents the closing-block protocol. This appends, so existing instructions are kept.
mkdir -p ~/.claude ~/.codex ~/.gemini
cat ~/aoe-chief/rules/communication.md >> ~/.claude/CLAUDE.md
cat ~/aoe-chief/rules/communication.md >> ~/.codex/AGENTS.md
cat ~/aoe-chief/rules/communication.md >> ~/.gemini/GEMINI.md    # Antigravity CLI (agy)

# Let any conversation hand its plan to Chief ("delegate to chief").
for f in ~/.claude/CLAUDE.md ~/.codex/AGENTS.md ~/.gemini/GEMINI.md; do printf '\n%s\n' "When I ask you to hand work off to AoE Chief, \
read ~/aoe-chief/rules/handoff.md and follow it. The Chief command is: python3 ~/aoe-chief/chief.py" >> "$f"; done
```

Most work starts in a conversation: once you and the agent agree on a plan, say "delegate to chief" and it writes
the task contract and starts a supervised worker. See [Handing off from a conversation](docs/guide.md#handing-off-from-a-conversation).

### 🎮 Try the demo (about 6 minutes)

`demo.sh` creates a small shop library with three bugs and delegates it to Codex. The worker is told to fix one
test per turn and to ask before choosing the receipt format. The demo state lives in its own directory, so your real
board stays clean.

What you will see, in order:

1. **Test approval** (🔴): the worker first strengthens the acceptance tests and asks you to approve them. Press `a`.
2. **Auto-continue**: the worker fixes one test per turn, and Chief sends the remaining failures back each time.
3. **A drafted decision** (📝): the worker asks "plain text or JSON?" and Chief drafts the answer. Press `a` to send
   it, or `r` to reply with your own.
4. **Cross review** (✅): once the checks pass, a second model reviews the diff and writes a review card. Accept with
   `c` then `y` in the inbox, or `chief close shop-demo`.

```bash
~/aoe-chief/demo.sh
export AOE_CHIEF_HOME=~/.local/state/aoe-chief-demo
chief watch --every 30          # terminal 2: let Chief drive
chief inbox                     # press a to accept a draft or explicitly approve pending tests
chief decide shop-demo:1 --accept   # the same from the command line
cat $AOE_CHIEF_HOME/tasks/shop-demo/review.md
chief close shop-demo           # or: chief nudge shop-demo "also format prices with 2 decimals"
~/aoe-chief/demo.sh clean
```

## 📅 Daily use

| Command | Use it to |
|---|---|
| `chief new "Fix the parser"` | Delegate a task with checks and a worker session |
| `chief adopt <session>` | Supervise an agreed plan in the existing conversation, in place |
| `chief watch --every 300` | Keep checks, continuation and reviews running |
| `chief inbox` | Handle questions, test approvals and reviews |
| `chief decide <decision-id> --accept` | Approve pending tests or accept a drafted decision |
| `chief close <task-id>` | Accept completed work and archive its session |

See the [guide](docs/guide.md) for decisions and cleanup, or the [command reference](docs/commands.md) for all commands.

## Supported agents

- **Claude** (`claude`): worker, AI briefs and decision drafts; reviews Codex work.
- **Codex** (`codex`): default worker, AI briefs and decision drafts; reviews Claude and Antigravity work.
- **Antigravity** (`antigravity`, CLI `agy`): worker supervised through native transcripts and terminal prompts.

See [agent details](docs/agents.md) for trust prompts, menus and transcript locations.

## 🛡️ Safety model

- Chief never pushes, merges or deploys; you own acceptance and irreversible decisions.
- Checks run as you; register only commands you trust.
- Transcripts, screens and diffs are untrusted data; secrets are masked before storage or forwarding.
- Folder trust is opt-in; worker approval menus and big decisions require you.

See the [full safety model](docs/guide.md#safety-model) and [agent permissions](docs/agents.md#trust-and-approval-prompts).

## Documentation

- [User guide](docs/guide.md): delegated tasks, decisions, closing, cleanup and thinking tasks.
- [Inbox and console](docs/inbox.md): navigation, delegation, AI questions, commands and standing sessions.
- [Command reference](docs/commands.md): commands, tick behavior and an example brief.
- [Configuration](docs/configuration.md): settings, agent wrappers and state layout.
- [Supported agents](docs/agents.md): trust prompts, update and approval menus, and transcripts.
- [Development](docs/development.md): tests and roadmap.
- [Architecture](docs/architecture.md): task supervision, design rationale and implementation notes.

## 🙏 Built on

- [Agent of Empires](https://github.com/agent-of-empires/agent-of-empires): the tmux-based session manager
  Chief supervises.
- [Codex CLI](https://github.com/openai/codex) and [Claude Code](https://github.com/anthropics/claude-code): the
  workers, and each other's reviewers.
- Antigravity CLI (`agy`): a third worker, supervised through its native transcripts and terminal prompts.

## 📄 License

[MIT](LICENSE) © 2026 Tianchi YU
