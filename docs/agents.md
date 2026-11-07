# Supported agents

[Back to README](../README.md) · [Task guide](guide.md) · [Wrapper configuration](configuration.md#launching-an-agent-through-a-wrapper)

## Choosing a worker

Choose a worker with `--tool codex`, `--tool claude`, or `--tool antigravity` (Codex is the default):

```bash
chief new "Make the parser accept trailing commas" --tool antigravity
```

Chief passes AoE's built-in tool name `antigravity` to `aoe add`; no custom tool or command override is needed.
The inbox contract editor also accepts `"tool": "antigravity"`. Antigravity is a worker only: `--engine` and
`chief engine` still offer `codex|claude`. Automatic session rotation requires a context percentage on screen;
Chief does not estimate an agy context window from token counts.

## Native transcripts

**Native transcripts.** Chief reads worker history locally:

| Worker | Transcript location |
|---|---|
| Claude | `$CLAUDE_CONFIG_DIR/projects/*/<session-id>.jsonl` (default base `~/.claude`); follows continuation chains |
| Codex | `$CODEX_HOME/sessions/*/*/*/rollout-*-<session-id>.jsonl` (default base `~/.codex`) |
| Antigravity (`agy`) | `~/.gemini/antigravity-cli/brain/<uuid>/.system_generated/logs/transcript.jsonl` |

## Trust and approval prompts

- 📁 **Trust prompts:** Codex, Claude, and Antigravity folder-trust prompts are answered only when the task has
  trust enabled (`--trust`, or the inbox trust toggle). Chief verifies the affirmative menu selection before
  confirming Antigravity's `Do you trust the contents of this project?` prompt.
- ✋ **Worker approvals:** Antigravity's `Accept this file edit?` and `Run this command?` menus require your
  action in the session. Chief reports waiting for approval and never accepts these menus, even with `--trust`.

## Claude

Claude Code uses the transcript location above and follows continuation chains.
Folder-trust prompts require task trust to be enabled, as described above.

## Codex

**Codex startup update menu:** `Update available · <old> → <new>` followed by `Update now` pauses kickoff.
Chief sends no menu keys, even with `--trust`. Accept the `codex-update` decision to run Chief's configured
update command (default: `npm install -g @openai/codex@{version} --prefix ~/.npm-global`), verify the binary,
and resume automatically. Codex's own `Update now` uses the wrong global prefix and is never selected.
A manual update or pressing `Esc` in the session also resumes automatically on tick.
The boxed `✨ Update available! <old> -> <new>` history banner left after Esc is informational; with the normal
input box, Codex is ready. A still-open update menu below that banner continues to block Chief.

## Antigravity

AoE does not store an `agent_session_id` for Antigravity. Chief resolves the session's absolute workspace path
in `~/.gemini/antigravity-cli/cache/last_conversations.json`, then reads that conversation's transcript and
`~/.gemini/antigravity-cli/annotations/<uuid>.pbtxt` title. Chief worktrees are unique per task. The mapping is
reread on each observation; Chief never selects another workspace's conversation as a fallback. Chief uses
agy's standard storage directory and does not define an undocumented `ANTIGRAVITY_HOME` environment override.

For agy prompts, only the `USER_REQUEST` body is shown; trailing metadata and settings blocks are excluded.
Untagged input is kept as raw text. The last planner response supplies the reply and closing block, while tool
calls and results update activity without masquerading as final replies. The same history feeds show, briefs,
decisions, auto-continue, recovery, and stuck detection. Missing history falls back to screen-based observation.

agy reads global rules from `~/.gemini/GEMINI.md` (or `~/.gemini/AGENTS.md`). Install the communication rules and
the hand-off line there, as in the [quick start](../README.md#-quick-start), so conversations with agy end with a
closing block and can hand work off to Chief.
