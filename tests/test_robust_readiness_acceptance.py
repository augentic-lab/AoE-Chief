"""Readiness is an agreement of independent signals, not a screen-wording guess.

These acceptance tests exercise wait_ready/deliver with real native transcript
parsers and temporary session records. Only terminal I/O and elapsed time are
simulated. No real AoE, tmux, subprocess, network, or wall-clock sleeps are used.

Proposed config contract: screen_patterns maps input/busy/menu to regex strings;
omitted entries retain their defaults. Tests intentionally avoid prescribing a
new readiness helper, a regex table's Python name, or an exact diagnostic format.
"""
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import chief
from test_busy_screen import CODEX_DONE, CODEX_WORKING
from test_codex_update_menu_acceptance import REAL_SCREEN as CODEX_UPDATE
from test_real_codex_trust_prompt import REAL_SCREEN as CODEX_TRUST


SID = "0123456789abcdef"
AGENT_SID = "12345678-1234-1234-1234-123456789abc"
MARKER = "AoE Chief: readiness acceptance delivery"
CLAUDE_INPUT = ("────────────────────────────────────────\n"
                "❯ \n"
                "────────────────────────────────────────\n"
                "  ? for shortcuts\n")
# Verbatim working/completed lines and menu reported from Claude Code 2.1.316;
# the normal input box below them is retained to reproduce false readiness.
CLAUDE_WORKING = "✽ Manifesting… (16s · ↓ 395 tokens)\n" + CLAUDE_INPUT
CLAUDE_DONE = "✻ Crunched for 28s · done 11:05 PM\n" + CLAUDE_INPUT
TEACH_MENU = ("Teach auto mode about your environment?\n"
              "  Auto mode works better when it knows your environment. Takes about a minute.\n"
              "  ❯ 1. Yes\n"
              "    2. Not now\n"
              "    3. Don't show again\n"
              "  Enter to confirm · Esc to cancel\n" + CLAUDE_INPUT)


class ReadinessFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        state = self.root / "chief"
        state.mkdir()
        paths = {"ROOT": state, "CFG": state / "config.json", "TASKS": state / "tasks",
                 "AOE_HOME": self.root / "aoe", "CLAUDE_HOME": self.root / "claude",
                 "CODEX_HOME": self.root / "codex", "ANTIGRAVITY_HOME": self.root / "agy"}
        self.stack.enter_context(mock.patch.multiple(chief, LANG="en", **paths))
        self.cfg = {"profile": "acceptance", "tracked_ids": [SID], "tasks": {}, "aoe_colors": False}
        self.task = {"id": "readiness", "name": "Readiness acceptance", "session_id": SID,
                     "state": "running", "tool": "claude", "goal": "Test readiness",
                     "repo": str(self.root), "worktree": str(self.root)}
        chief.save_task(self.task)
        chief.save_cfg(self.cfg)
        # Fail closed if a future implementation accidentally escapes the fixture.
        for name in ("call", "tmux_target", "answer_trust_menu"):
            self.stack.enter_context(mock.patch.object(
                chief, name, side_effect=AssertionError("unexpected external action: " + name)))
        for name in ("run", "Popen", "call", "check_call", "check_output"):
            self.stack.enter_context(mock.patch.object(
                chief.subprocess, name, side_effect=AssertionError("unexpected subprocess: " + name)))
        self.stack.enter_context(mock.patch.object(
            chief.os, "system", side_effect=AssertionError("unexpected shell execution")))
        self.stack.enter_context(mock.patch.object(
            chief.threading.Thread, "start", side_effect=AssertionError("unexpected worker")))
        self.select_tool("claude")

    def select_tool(self, tool):
        self.tool = tool
        self.rec = dict(self.task, id=SID, tool=tool, project_path=str(self.root), status="waiting")
        if tool != "antigravity":
            self.rec["agent_session_id"] = AGENT_SID
        records = chief.AOE_HOME / "profiles" / "acceptance" / "sessions.json"
        records.parent.mkdir(parents=True, exist_ok=True)
        records.write_text(json.dumps([self.rec]), encoding="utf-8")
        if tool == "claude":
            self.path = chief.CLAUDE_HOME / "projects" / "fixture" / (AGENT_SID + ".jsonl")
        elif tool == "codex":
            self.path = chief.CODEX_HOME / "sessions" / "2026" / "11" / "02" / (
                "rollout-2026-11-02T00-00-00-" + AGENT_SID + ".jsonl")
        else:
            self.path = chief.ANTIGRAVITY_HOME / "brain" / AGENT_SID / ".system_generated" / "logs" / "transcript.jsonl"
            mapping = chief.ANTIGRAVITY_HOME / "cache" / "last_conversations.json"
            mapping.parent.mkdir(parents=True, exist_ok=True)
            mapping.write_text(json.dumps({str(self.root): AGENT_SID}), encoding="utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows = []

    def append(self, kind, text=""):
        ts = "2026-11-02T00:00:{:02d}Z".format(len(self.rows))
        if self.tool == "claude":
            if kind == "prompt":
                row = {"type": "user", "message": {"role": "user", "content": text}}
            else:
                row = {"type": "assistant", "message": {"role": "assistant",
                       "content": [{"type": "text", "text": text or "Finished."}],
                       "stop_reason": "end_turn" if kind == "done" else None}}
                if kind == "error":
                    row["isApiErrorMessage"] = True
            row["timestamp"] = ts
        elif self.tool == "codex":
            if kind in ("prompt", "reply"):
                row = {"type": "response_item", "payload": {"type": "message",
                       "role": "user" if kind == "prompt" else "assistant",
                       "content": [{"type": "input_text" if kind == "prompt" else "output_text", "text": text}]}}
            else:
                row = {"type": "event_msg", "payload": {
                    "type": "task_complete" if kind == "done" else "error", "message": text}}
            row["timestamp"] = ts
        else:
            row = {"type": "USER_INPUT" if kind == "prompt" else "PLANNER_RESPONSE",
                   "content": text or "Finished.", "created_at": ts,
                   "status": "DONE" if kind == "done" else "RUNNING"}
        self.rows.append(row)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")

    def seed(self, state="done", prompt="Previous request"):
        self.append("prompt", prompt)
        if state != "open":
            self.append(state)
        self.assertEqual(chief.transcript(self.rec)["turn"], state,
                         "fixture must exercise the real native transcript parser")

    @contextmanager
    def terminal(self, frames=CODEX_DONE, status="waiting", on_sleep=None):
        frames = [frames] if isinstance(frames, str) or frames is None else frames
        self.elapsed, self.capture_times, self.sent = 0.0, [], []
        output = io.StringIO()

        def sleep(seconds):
            self.assertGreaterEqual(seconds, 0)
            self.elapsed += seconds
            self.assertLessEqual(self.elapsed, 60, "polling must be bounded")
            if on_sleep:
                on_sleep(self.elapsed)

        def capture(*args):
            index = min(len(self.capture_times), len(frames) - 1)
            self.capture_times.append(self.elapsed)
            return frames[index]

        def aoe(cfg, *args, **kwargs):
            if args == ("session", "show", "--json", SID):
                current = status(self.elapsed) if callable(status) else status
                return json.dumps(dict(self.rec, status=current))
            if len(args) == 3 and args[:2] == ("send", SID):
                self.sent.append(args[2])
                return ""
            self.fail("unexpected AoE action: {!r}".format(args))

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(chief, "aoe", side_effect=aoe))
            stack.enter_context(mock.patch.object(chief, "screen", side_effect=capture))
            stack.enter_context(mock.patch.object(chief.time, "time", side_effect=lambda: self.elapsed))
            stack.enter_context(mock.patch.object(chief.time, "monotonic", side_effect=lambda: self.elapsed))
            stack.enter_context(mock.patch.object(chief.time, "sleep", side_effect=sleep))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(output))
            yield
        events = chief.TASKS / self.task["id"] / "events.jsonl"
        self.diagnostics = output.getvalue() + (events.read_text(encoding="utf-8") if events.exists() else "")

    def observe(self, frames=CODEX_DONE, status="waiting", timeout=0, on_sleep=None, cfg=None):
        with self.terminal(frames, status, on_sleep):
            result = chief.wait_ready(self.cfg if cfg is None else cfg, SID, False, timeout=timeout)
        self.assertEqual(self.sent, [], "readiness observation must never type into a menu")
        return result


class RobustReadinessAcceptanceTests(ReadinessFixture):
    def test_open_native_turn_vetoes_a_ready_screen_for_every_tool(self):
        for tool in ("claude", "codex", "antigravity"):
            with self.subTest(tool=tool):
                self.select_tool(tool)
                self.seed("open")
                for timeout in (0, 6):
                    with self.subTest(timeout=timeout):
                        self.assertEqual(self.observe(timeout=timeout), "timeout")

    def test_new_claude_working_line_without_interrupt_hint_is_not_ready(self):
        self.seed("open")
        self.assertNotIn("esc to interrupt", CLAUDE_WORKING)
        self.assertEqual(self.observe(CLAUDE_WORKING), "timeout")

    def test_closed_turns_and_finished_screens_can_be_ready(self):
        for tool, frame in (("claude", CLAUDE_DONE), ("codex", CODEX_DONE), ("antigravity", CODEX_DONE)):
            with self.subTest(tool=tool):
                self.select_tool(tool)
                self.seed()
                self.assertEqual(self.observe(frame), "ready")

    def test_error_is_a_closed_turn_not_an_open_turn(self):
        self.seed("error")
        self.assertEqual(self.observe(CLAUDE_DONE), "ready")

    def test_no_transcript_allows_brand_new_session_when_other_signals_agree(self):
        self.assertIsNone(chief.transcript(self.rec))
        self.assertEqual(self.observe(), "ready")

    def test_aoe_idle_or_waiting_remains_required_even_with_closed_transcript(self):
        self.seed()
        for status in ("idle", "waiting", "running", "stopped", "starting", None):
            with self.subTest(status=status):
                self.assertEqual(self.observe(status=status), "ready" if status in ("idle", "waiting") else "timeout")

    def test_single_observation_takes_two_captures_about_two_seconds_apart(self):
        self.seed()
        self.assertEqual(self.observe(), "ready")
        self.assertEqual(len(self.capture_times), 2)
        self.assertGreaterEqual(self.capture_times[1] - self.capture_times[0], 1.5)
        self.assertLessEqual(self.elapsed, 3.0)

    def test_unknown_changing_output_vetoes_readiness_with_or_without_transcript(self):
        for has_transcript in (False, True):
            if has_transcript:
                self.seed()
            for timeout in (0, 2):
                with self.subTest(transcript=has_transcript, timeout=timeout):
                    frames = ["Unfamiliar glyph ◇ 17\n" + CODEX_DONE, "Unfamiliar glyph ◆ 18\n" + CODEX_DONE]
                    self.assertEqual(self.observe(frames, timeout=timeout), "timeout")
                    self.assertGreaterEqual(len(self.capture_times), 2)
                    self.assertLessEqual(self.elapsed, 3.0)

    def test_quiescence_strips_trailing_whitespace_on_each_line(self):
        self.seed()
        padded = "\n".join(line.rstrip() + " \t" for line in CODEX_DONE.splitlines()) + "\n"
        self.assertEqual(self.observe([CODEX_DONE, padded]), "ready")

    def test_polling_can_recover_after_output_settles(self):
        self.seed()
        self.assertEqual(self.observe(["Frame A\n" + CODEX_DONE, "Frame B\n" + CODEX_DONE,
                                       CODEX_DONE, CODEX_DONE], timeout=12), "ready")
        self.assertGreaterEqual(len(self.capture_times), 4)

    def test_status_is_rechecked_after_quiescence_wait(self):
        self.seed()
        self.assertEqual(self.observe(status=lambda elapsed: "waiting" if elapsed == 0 else "running"), "timeout")

    def test_transcript_is_rechecked_after_quiescence_wait(self):
        self.seed()
        def start_turn(elapsed):
            if len(self.rows) == 2:
                self.append("prompt", "Human started another turn")
        self.assertEqual(self.observe(on_sleep=start_turn), "timeout")

    def test_teach_auto_mode_menu_over_input_box_vetoes_closed_transcript(self):
        self.seed()
        for timeout in (0, 6):
            with self.subTest(timeout=timeout):
                self.assertEqual(self.observe(TEACH_MENU, timeout=timeout), "timeout")

    def test_numbered_cursor_menus_do_not_depend_on_heading_or_option_words(self):
        self.seed()
        for cursor in ("❯", "›", ">"):
            for selected in (1, 2):
                with self.subTest(cursor=cursor, selected=selected):
                    menu = "A future CLI question\n" + "\n".join(
                        "{} {}. {}".format(cursor if n == selected else " ", n, label)
                        for n, label in ((1, "Proceed with frobnication"), (2, "Later")))
                    self.assertEqual(self.observe(menu + "\n" + CLAUDE_INPUT), "timeout")

    def test_approval_options_veto_without_a_known_question(self):
        self.seed()
        self.assertEqual(self.observe("Action requested\n> 1. Yes, run command\n  2. No\n" + CLAUDE_INPUT), "timeout")

    def test_plain_numbered_reply_and_distant_menu_history_do_not_own_keyboard(self):
        self.seed()
        for history in ("1. First result\n2. Second result\n",
                        TEACH_MENU + "Earlier output\n" * 80):
            with self.subTest(history=history[:30]):
                self.assertEqual(self.observe(history + CLAUDE_DONE), "ready")

    def test_existing_codex_busy_pattern_is_an_independent_veto(self):
        self.seed()
        self.assertEqual(self.observe(CODEX_WORKING), "timeout")

    def test_update_and_trust_keep_their_public_return_values_without_interaction(self):
        self.seed("open")
        for frame, expected in ((CODEX_UPDATE, "update"), (CODEX_TRUST, "trust")):
            for timeout in (0, 12):
                with self.subTest(expected=expected, timeout=timeout):
                    self.assertEqual(self.observe(frame + CLAUDE_INPUT, timeout=timeout), expected)

    def test_missing_input_or_missing_capture_is_not_ready(self):
        self.seed()
        for frame in (None, "", "Agent finished, but the input box is not visible"):
            with self.subTest(frame=frame):
                self.assertEqual(self.observe(frame), "timeout")

    def test_config_json_overrides_each_screen_pattern_and_retains_other_defaults(self):
        self.seed()
        cases = (("busy", r"(?m)^Quantum operation pending$", "Quantum operation pending\n" + CODEX_DONE, "timeout"),
                 ("input", r"(?m)^NEW INPUT>$", "NEW INPUT>\n", "ready"),
                 ("menu", r"(?m)^Choose using arrow keys$", "Choose using arrow keys\n" + CODEX_DONE, "timeout"))
        for key, pattern, frame, expected in cases:
            with self.subTest(key=key):
                chief.save_cfg(dict(self.cfg, screen_patterns={key: pattern}))
                cfg = chief.config()
                self.assertEqual(self.observe(frame, cfg=cfg), expected)
                self.assertEqual(self.observe(CODEX_DONE), "ready", "config override must not leak to other calls")
                busy_frame = CODEX_WORKING if key != "input" else "NEW INPUT>\nesc to interrupt\n"
                if key != "busy":
                    self.assertEqual(self.observe(busy_frame, cfg=cfg), "timeout")
        self.assertEqual(self.observe(), "ready", "per-call config must not mutate defaults")

    def test_permissive_patterns_cannot_override_structured_or_quiescence_vetoes(self):
        cfg = dict(self.cfg, screen_patterns={"input": r"[\s\S]+", "busy": r"(?!)", "menu": r"(?!)"})
        self.seed("open")
        self.assertEqual(self.observe(cfg=cfg), "timeout")
        self.append("done")
        self.assertEqual(self.observe(status="running", cfg=cfg), "timeout")
        self.assertEqual(self.observe(["unknown A", "unknown B"], cfg=cfg), "timeout")

    def test_blocked_signal_is_diagnosable_in_events_or_output(self):
        cases = (("open", "waiting", CODEX_DONE, r"(?i)transcript[^\n]{0,80}open|open[^\n]{0,80}(?:transcript|turn)"),
                 ("done", "running", CODEX_DONE, r"(?i)status"),
                 ("done", "waiting", ["A\n" + CODEX_DONE, "B\n" + CODEX_DONE], r"(?i)screen[ _:-]*chang|quiescen"),
                 ("done", "waiting", TEACH_MENU, r"(?i)menu"),
                 ("done", "waiting", CODEX_WORKING, r"(?i)pattern|busy"))
        for state, status, frames, reason in cases:
            with self.subTest(reason=reason):
                if self.path.exists():
                    self.path.unlink()
                self.rows = []
                events = chief.TASKS / self.task["id"] / "events.jsonl"
                if events.exists():
                    events.unlink()
                self.seed(state)
                self.assertEqual(self.observe(frames, status=status), "timeout")
                self.assertRegex(self.diagnostics, reason)

    def test_configuration_documentation_explains_screen_patterns(self):
        doc = (Path(__file__).resolve().parents[1] / "docs" / "configuration.md").read_text(encoding="utf-8")
        self.assertIn("screen_patterns", doc)
        for key in ("input", "busy", "menu"):
            self.assertRegex(doc, r'["`]' + key + r'["`]')


class TranscriptDeliveryAcceptanceTests(ReadinessFixture):
    def send(self, frames=CODEX_DONE, status="waiting", on_sleep=None):
        with self.terminal(frames, status, on_sleep):
            result = chief.deliver(self.cfg, SID, MARKER + "\nPlease continue.", MARKER)
        self.assertEqual(self.sent, [MARKER + "\nPlease continue."], "send exactly once, including on timeout")
        self.assertLessEqual(self.elapsed, 48)
        return result

    def test_new_native_user_prompt_confirms_delivery_without_screen_or_running_status(self):
        for tool in ("claude", "codex", "antigravity"):
            with self.subTest(tool=tool):
                self.select_tool(tool)
                self.seed()
                def receive(elapsed):
                    if len(self.rows) == 2:
                        self.append("prompt", MARKER + "\nPlease continue.")
                self.assertTrue(self.send(on_sleep=receive))
                self.assertLessEqual(self.elapsed, 9, "confirmation should not wait out the timeout")

    def test_screen_echo_and_running_status_cannot_confirm_existing_transcript(self):
        self.seed()
        for frame, status in ((CODEX_DONE, "running"), (MARKER + "\n" + CODEX_DONE, "waiting"),
                              (MARKER + "\n" + CODEX_DONE, "running")):
            with self.subTest(status=status, marker_on_screen=MARKER in frame):
                self.assertFalse(self.send(frame, status))

    def test_waits_for_delayed_user_prompt_despite_early_running_status(self):
        self.seed()
        def receive(elapsed):
            if elapsed >= 9 and len(self.rows) == 2:
                self.append("prompt", MARKER)
        self.assertTrue(self.send(status="running", on_sleep=receive))
        self.assertGreaterEqual(self.elapsed, 9)

    def test_old_matching_prompt_and_new_assistant_echo_are_not_delivery(self):
        self.seed(prompt=MARKER)
        def echo(elapsed):
            if len(self.rows) == 2:
                self.append("reply", MARKER)
                self.append("done")
        self.assertFalse(self.send(MARKER + "\n" + CODEX_DONE, "running", echo))

    def test_new_matching_prompt_counts_even_when_same_marker_was_used_before(self):
        self.seed(prompt=MARKER)
        def receive(elapsed):
            if len(self.rows) == 2:
                self.append("prompt", MARKER)
        self.assertTrue(self.send(on_sleep=receive))

    def test_new_unrelated_user_prompt_does_not_confirm_marker(self):
        self.seed()
        def unrelated(elapsed):
            if len(self.rows) == 2:
                self.append("prompt", "An unrelated human request")
        self.assertFalse(self.send(MARKER + "\n" + CODEX_DONE, "running", unrelated))

    def test_transcript_disappearing_after_send_does_not_enable_unsafe_fallback(self):
        self.seed()
        def disappear(elapsed):
            if self.path.exists():
                self.path.unlink()
        self.assertFalse(self.send(MARKER, "running", disappear))

    def test_without_transcript_screen_or_status_confirmation_remains_available(self):
        self.assertIsNone(chief.transcript(self.rec))
        for frame, status, expected in ((CODEX_DONE, "running", True),
                                        (MARKER + "\n" + CODEX_DONE, "waiting", True),
                                        (CODEX_DONE, "waiting", False)):
            with self.subTest(status=status, expected=expected):
                self.assertEqual(self.send(frame, status), expected)

    def test_unconfirmed_kickoff_needs_user_and_never_retries(self):
        self.seed()
        kickoff_marker = "delegated task managed by AoE Chief"
        with self.terminal(kickoff_marker + "\n" + CODEX_DONE, "running"), \
                mock.patch.object(chief, "kickoff_prompt", return_value=kickoff_marker):
            chief.send_kickoff(self.cfg, self.task)
        self.assertEqual(self.task["state"], "needs-you")
        saved = json.loads((chief.TASKS / self.task["id"] / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "needs-you")
        self.assertEqual(self.sent, [kickoff_marker])


if __name__ == "__main__":
    unittest.main()
