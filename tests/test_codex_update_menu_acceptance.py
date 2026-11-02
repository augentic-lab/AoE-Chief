"""Codex startup updates require the user; Chief must only observe the menu.

Exercise the existing string-valued wait_ready interface and all three reporting
paths. Only terminal/process boundaries are simulated; no detector API is imposed.
"""
from contextlib import contextmanager, ExitStack
from pathlib import Path
from documentation_support import read_documentation
import json
import re
from types import SimpleNamespace
import unittest
from unittest import mock

import chief
from test_intent_task_flow import ChiefFixture
from test_real_claude_trust_prompt import REAL_SCREEN as CLAUDE_TRUST_SCREEN
from test_real_codex_trust_prompt import REAL_SCREEN as CODEX_TRUST_SCREEN


# Exact ANSI-stripped screen captured from Codex 0.162.1, including its marker,
# numbering, command explanation and footer. Do not replace with an ideal menu.
REAL_SCREEN = """  Update available · 0.162.1 → 0.165.0
  Release notes: https://github.com/openai/codex/releases/latest
› 1. Update now (runs `npm install -g @openai/codex`)
  2. Skip
  3. Skip until next version
  enter continue · esc skip
"""
# Real Codex 0.162.1 screen after the user pressed Esc. Only decorative
# ASCII-art logo lines were omitted; the history banner and rest are verbatim.
AFTER_SKIP_SCREEN = """╭─────────────────────────────────────────────────╮
│ ✨ Update available! 0.162.1 -> 0.165.0         │
│ Run npm install -g @openai/codex to update.     │
│                                                 │
│ See full release notes:                         │
│ https://github.com/openai/codex/releases/latest │
╰─────────────────────────────────────────────────╯
  >_ OpenAI Codex (v0.162.1)
     ~/.claude/jobs/e5acd660/tmp/codexprobe2-1793196696

› Ask Codex to do anything

  GPT-6.1-Sol xhigh · ~/.claude/jobs/e5acd660/tmp/codexprobe2-1793196696 · Context 0% used · weekly 99% left
  ← for agents · ? for shortcuts
"""
UPDATE_BANNER = AFTER_SKIP_SCREEN.split("  >_ OpenAI Codex", 1)[0]
HEADING = REAL_SCREEN.splitlines()[0].strip()
OPTION = REAL_SCREEN.splitlines()[2]
READY = "› Ask Codex to do anything\n"
SID = "0123456789abcdef"
OLD_SID = "fedcba9876543210"
LAUNCH = "aoe-update-acceptance"


@contextmanager
def terminal(test, screens=REAL_SCREEN, status="waiting", launch=None, stop=False):
    """Record every external action and forbid all keys/commands except setup.

    A fake clock makes broken detection fail promptly rather than waiting for a
    real timeout. Guards cover direct subprocess/OS execution as well as Chief's
    usual call/aoe wrappers, so no upgrade or skip can escape through another API.
    """
    frames = [screens] if isinstance(screens, str) or screens is None else list(screens)
    captures = iter(frames)
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    def aoe(cfg, *args, **kwargs):
        if args == ("session", "show", "--json", SID):
            return json.dumps({"status": status})
        if stop and args == ("session", "stop", OLD_SID):
            return ""
        test.fail("unexpected AoE action (including start/send/upgrade): {!r}".format(args))

    def call(command, **kwargs):
        if launch is not None and command == launch:
            return "ID: {}\nPath: /tmp/update-acceptance-worktree\n".format(SID)
        test.fail("unexpected command (including keys or upgrade): {!r}".format(command))

    io = SimpleNamespace(forbidden=[])
    with ExitStack() as stack:
        io.aoe = stack.enter_context(mock.patch.object(chief, "aoe", side_effect=aoe))
        io.call = stack.enter_context(mock.patch.object(chief, "call", side_effect=call))
        io.capture = stack.enter_context(mock.patch.object(
            chief, "screen", side_effect=lambda *args: next(captures, frames[-1])))
        io.sleep = stack.enter_context(mock.patch.object(chief.time, "sleep", side_effect=sleep))
        stack.enter_context(mock.patch.object(chief.time, "time", side_effect=lambda: clock[0]))
        for name in ("tmux_target", "answer_trust_menu", "send_kickoff", "deliver"):
            io.forbidden.append(stack.enter_context(mock.patch.object(
                chief, name, side_effect=AssertionError("must not invoke " + name))))
        io.forbidden.append(stack.enter_context(mock.patch.object(
            chief.threading.Thread, "start", side_effect=AssertionError("must not start a worker"))))
        for name in ("run", "Popen", "call", "check_call", "check_output"):
            io.forbidden.append(stack.enter_context(mock.patch.object(
                chief.subprocess, name, side_effect=AssertionError("must not execute " + name))))
        io.forbidden.append(stack.enter_context(mock.patch.object(
            chief.os, "system", side_effect=AssertionError("must not execute an upgrade or keys"))))
        yield io


def assert_no_intervention(io):
    for action in io.forbidden:
        action.assert_not_called()


class CodexUpdateDetectionTests(unittest.TestCase):
    def observe(self, text, trust=False, timeout=0, expected="update", status="waiting"):
        with terminal(self, text, status=status) as io:
            result = chief.wait_ready({"profile": "acceptance"}, SID, trust, timeout=timeout)
        self.assertEqual(result, expected)
        self.assertIsInstance(result, str, "retain wait_ready's string result interface")
        if expected in ("update", "trust"):
            self.assertEqual(io.capture.call_count, 1, "special menus still return immediately")
            io.aoe.assert_called_once_with({"profile": "acceptance"}, "session", "show", "--json", SID)
            io.sleep.assert_not_called()
        else:
            self.assertGreaterEqual(io.capture.call_count, 2, "ordinary readiness needs a quiescence sample")
            if timeout <= 0:
                elapsed = sum(call[0][0] for call in io.sleep.call_args_list)
                self.assertGreaterEqual(elapsed, 1.5)
                self.assertLessEqual(elapsed, 3)
        io.call.assert_not_called()
        assert_no_intervention(io)
        return result

    def reject(self, text):
        # These cases reject the *specific update detector*. A surviving numbered
        # cursor menu must now veto readiness generically, even if its heading is
        # quoted or unrecognized. Do not equate "not update" with "ready".
        self.assertIsNone(chief.UPDATE_RE.search(text + "\n" + READY))

    def test_exact_real_screen_in_both_timeout_modes_with_either_trust_setting(self):
        for timeout in (0, -1, 12):
            for trust in (False, True):
                with self.subTest(timeout=timeout, trust=trust):
                    self.observe(REAL_SCREEN, trust=trust, timeout=timeout)

    def test_real_post_skip_history_banner_is_ready_without_keys_in_both_timeout_modes(self):
        for timeout in (0, -1, 12):
            for trust in (False, True):
                for status in ("idle", "waiting"):
                    with self.subTest(timeout=timeout, trust=trust, status=status):
                        self.observe(AFTER_SKIP_SCREEN, trust=trust, timeout=timeout,
                                     status=status, expected="ready")

    def test_real_history_banner_above_open_menu_still_returns_update_without_keys(self):
        for timeout in (0, -1, 12):
            for trust in (False, True):
                for status in ("idle", "waiting"):
                    with self.subTest(timeout=timeout, trust=trust, status=status):
                        self.observe(UPDATE_BANNER + REAL_SCREEN, trust=trust,
                                     timeout=timeout, status=status)

    def test_whitespace_and_both_terminal_border_styles_are_accepted(self):
        for frame in ("{}", " \t{}\t ", "  │ {} │  ", "  ┃ {} ┃  ", "│ {}", "{} ┃"):
            for newline in ("\n", "\r\n"):
                with self.subTest(frame=frame, newline=repr(newline)):
                    text = newline.join(frame.format(line) for line in REAL_SCREEN.splitlines()) + newline
                    self.observe(text)
        self.observe(REAL_SCREEN.replace(HEADING, "Update available\t·\t0.162.1 \t→\t 0.165.0"))

    def test_menu_option_can_be_selected_or_unselected_and_have_its_command_explanation(self):
        for explanation in (True, False):
            for selected in (1, 2, 3):
                with self.subTest(explanation=explanation, selected=selected):
                    text = REAL_SCREEN
                    if not explanation:
                        text = text.replace(" (runs `npm install -g @openai/codex`)", "")
                    if selected != 1:
                        text = text.replace("› 1.", "  1.").replace("  {}.".format(selected), "› {}.".format(selected))
                    self.observe(text)

    def test_update_option_must_follow_with_at_most_three_intervening_lines(self):
        for filler in ("release details", "", "  │   │  "):
            for gap in range(6):
                with self.subTest(gap=gap, filler=filler):
                    text = HEADING + "\n" + (filler + "\n") * gap + OPTION + "\n"
                    if gap <= 3:
                        self.observe(text)
                    else:
                        self.reject(text)

    def test_heading_alone_or_only_skip_options_are_insufficient(self):
        for text in (HEADING, HEADING + "\nRelease notes: https://example.invalid\n",
                     REAL_SCREEN.replace(OPTION + "\n", ""), OPTION + "\n" + HEADING):
            with self.subTest(text=text):
                self.observe(text, expected="timeout")
                self.reject(text)

    def test_quoted_prose_and_reply_headings_do_not_block_readiness(self):
        for heading in (
                '"' + HEADING + '"', "'" + HEADING + "'", "`" + HEADING + "`",
                "> " + HEADING, "  > " + HEADING, "› " + HEADING, "❯ " + HEADING,
                "- " + HEADING, "Earlier the agent said: " + HEADING,
                "The reply mentions " + HEADING, HEADING + " is an example.",
                HEADING + '"', HEADING + " (as mentioned in the reply)"):
            with self.subTest(heading=heading):
                self.reject(REAL_SCREEN.replace("  " + HEADING, heading))

    def test_incomplete_or_nonmatching_headings_are_rejected(self):
        for heading in ("Update available", "Update available · 0.162.1 →",
                        "Update available · → 0.165.0", "Update available · 0.162.1",
                        "Update available · old → new", "Update available · 0.162.1 -> 0.165.0",
                        "Update available · 0.162.1 → 0.165.0 extra",
                        "Update available · 0.162.1\n → 0.165.0",
                        "Update available ·\n0.162.1 → 0.165.0"):
            with self.subTest(heading=heading):
                self.reject(REAL_SCREEN.replace("  " + HEADING, heading))

    def test_update_now_must_be_an_anchored_menu_option_not_a_mention(self):
        for option in ('"' + OPTION + '"', "> " + OPTION, "Earlier: " + OPTION,
                       "The reply says Update now", "1. Update nowadays",
                       "1. Update now is an example of a menu option."):
            with self.subTest(option=option):
                self.reject(REAL_SCREEN.replace(OPTION, option))

    def test_distant_options_cannot_supply_a_missing_option_for_another_heading(self):
        text = HEADING + "\n" + "details\n" * 4 + OPTION + "\n" + HEADING + "\n"
        self.reject(text)

    def test_update_precedes_readiness_and_real_trust_prompts_without_any_keys(self):
        for timeout in (0, 12):
            for trust in (False, True):
                for cue in (READY, "Trust this folder?\n", CODEX_TRUST_SCREEN, CLAUDE_TRUST_SCREEN,
                            CODEX_TRUST_SCREEN + CLAUDE_TRUST_SCREEN + READY):
                    for text in (REAL_SCREEN + cue, cue + REAL_SCREEN):
                        with self.subTest(timeout=timeout, trust=trust, cue=cue[:45], update_first=text.startswith(REAL_SCREEN)):
                            self.observe(text, trust=trust, timeout=timeout, status="idle")

    def test_normal_polling_returns_as_soon_as_update_appears(self):
        for trust in (False, True):
            with self.subTest(trust=trust), terminal(self, ["Starting Codex...\n", REAL_SCREEN]) as io:
                result = chief.wait_ready({"profile": "acceptance"}, SID, trust, timeout=12)
                self.assertEqual(result, "update")
                self.assertEqual(io.capture.call_count, 2)
                self.assertGreaterEqual(sum(call[0][0] for call in io.sleep.call_args_list), 1.5)
                self.assertLessEqual(sum(call[0][0] for call in io.sleep.call_args_list), 3)
                io.call.assert_not_called()
                assert_no_intervention(io)

    def test_zero_timeout_only_observes_and_never_starts_workers_or_answers_prompts(self):
        for timeout in (0, -1):
            for trust in (False, True):
                for text, status, expected in ((READY, "idle", "ready"),
                                               (CODEX_TRUST_SCREEN, "waiting", "trust"),
                                               (CLAUDE_TRUST_SCREEN, "waiting", "trust"),
                                               ("", "stopped", "timeout")):
                    with self.subTest(timeout=timeout, trust=trust, expected=expected):
                        self.observe(text, trust=trust, timeout=timeout, status=status, expected=expected)


class CodexUpdateMessageTests(ChiefFixture):
    def task(self, trust):
        return {"id": "codex-update", "name": "Codex update acceptance", "goal": "wait safely",
                "repo": str(self.repo), "worktree": str(self.repo), "branch": "chief/codex-update",
                "tool": "codex", "state": "draft", "trust": trust}

    def report(self, path, lang="en", trust=False, screens=REAL_SCREEN, readiness=None):
        """Use real lifecycle/readiness code, except a supplied string result.

        A supplied result models a menu disappearing between readiness detection
        and message construction, without changing wait_ready's interface.
        """
        task = self.task(trust)
        if path != "start":
            task.update(state="running", session_id=OLD_SID if path == "rotate" else SID)
        chief.save_task(task)
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(chief, "LANG", lang))
            stack.enter_context(mock.patch.object(chief, "aoe_bin", return_value=LAUNCH))
            stack.enter_context(mock.patch.object(chief, "add_command", return_value=[LAUNCH, "add", "--launch"]))
            stack.enter_context(mock.patch.object(chief, "aoe_records", return_value={SID: {"project_path": str(self.repo)}}))
            stack.enter_context(mock.patch.object(chief, "git_head", return_value="a" * 40))
            stack.enter_context(mock.patch.object(chief, "prepare_worktree"))
            if readiness is not None:
                stack.enter_context(mock.patch.object(chief, "wait_ready", return_value=readiness))
            launch = None
            if path == "start":
                launch = [LAUNCH, "add", "--launch"]
            elif path == "rotate":
                launch = [LAUNCH, "-p", self.cfg["profile"], "add", str(self.repo),
                          "-t", task["name"] + " #2", "--tool", "codex", "--launch"]
            io = stack.enter_context(terminal(self, screens, launch=launch, stop=path == "rotate"))
            if path == "start":
                result = chief.start_task(self.cfg, task, trust)
                self.assertEqual(result["state"], "needs-you")
                message = result["note"]
            elif path == "rotate":
                chief.rotate_task(self.cfg, task, {"log": {"turns_total": 3}}, "acceptance rotation")
                self.assertEqual(task["state"], "needs-you")
                self.assertEqual(task["session_id"], SID)
                message = task["note"]
            else:
                code, out, err = self.cli("kickoff", task["id"], *(["--trust"] if trust else []))
                self.assertEqual(code, 1, out + err)
                self.assertNotIn("Task codex-update · running", out)
                message = err.strip()
            if path != "kickoff":
                saved = chief.load_task(task["id"])
                self.assertEqual(saved["state"], "needs-you")
                self.assertEqual(saved["note"], message)
            io.sleep.assert_not_called()
            assert_no_intervention(io)
        return message

    def assert_update_message(self, text, path, lang, versions=("0.162.1", "0.165.0")):
        command = "chief.py {} codex-update".format("nudge" if path == "rotate" else "kickoff")
        self.assertIn(command, text)
        self.assertIn("Esc", text)
        self.assertNotIn("chief.py {} codex-update".format("kickoff" if path == "rotate" else "nudge"), text)
        if lang == "en":
            self.assertRegex(text, r"(?i)Codex[^.\n]*(?:offer|update)")
            self.assertRegex(text, r"(?i)Chief\s+(?:will\s+)?never\s+(?:updat|upgrad)(?:e[sd]?|ing)[^.;\n]*skip")
            self.assertRegex(text, r"(?i)(?:upgrad|updat)e\s+Codex\s+(?:yourself|manually)")
            self.assertRegex(text, r"(?i)(?:skip|dismiss)[^.;\n]*Esc")
            self.assertRegex(text, r"(?i)session")
        else:
            self.assertRegex(text, r"Codex[^\n]*(?:更新|升级)")
            self.assertRegex(text, r"Chief[^\n]*(?:从不|不会)[^\n]*(?:更新|升级)[^\n]*跳过")
            self.assertRegex(text, r"(?:自行|自己|手动)[^\n]*(?:升级|更新)[^\n]*Codex")
            self.assertRegex(text, r"会话[^\n]*(?:Esc[^\n]*跳过|跳过[^\n]*Esc)")
        if versions is None:
            self.assertNotRegex(text, r"\d+\.\d+\.\d+", "missing versions must never be invented")
            self.assertNotRegex(text, r"(?i)\b(?:None|unknown|null)\s*(?:→|to)\s*(?:None|unknown|null)\b")
            if lang == "en":
                self.assertRegex(text, r"(?i)Codex\s+(?:is\s+)?offering\s+an?\s+update")
            return
        old, new = versions
        self.assertRegex(text, re.escape(old) + r"[\s\S]*" + re.escape(new))
        if lang == "en":
            self.assertRegex(text, r"(?i)from\s+" + re.escape(old) + r"\s+to\s+" + re.escape(new))
        else:
            self.assertRegex(text, r"从\s*" + re.escape(old) + r"\s*(?:到|至|升级到|更新到)\s*" + re.escape(new))

    def test_all_three_paths_report_real_versions_policy_and_correct_recovery_in_both_languages(self):
        for path in ("start", "rotate", "kickoff"):
            for lang in ("en", "zh"):
                for trust in (False, True):
                    with self.subTest(path=path, lang=lang, trust=trust):
                        self.assert_update_message(self.report(path, lang, trust), path, lang)

    def test_history_banner_above_open_menu_preserves_versions_in_all_three_message_paths(self):
        for path in ("start", "rotate", "kickoff"):
            for lang in ("en", "zh"):
                for trust in (False, True):
                    with self.subTest(path=path, lang=lang, trust=trust):
                        text = self.report(path, lang, trust, screens=UPDATE_BANNER + REAL_SCREEN)
                        self.assert_update_message(text, path, lang, versions=("0.162.1", "0.165.0"))

    def test_versions_are_extracted_from_observed_screen_including_bordered_forms(self):
        versions = ("1.23.4", "2.34.5")
        screen = REAL_SCREEN.replace("0.162.1", versions[0]).replace("0.165.0", versions[1])
        screen = "\n".join("  ┃ " + line + " ┃  " for line in screen.splitlines()) + "\n"
        screen = 'The reply quoted "Update available · 9.8.7 → 9.8.8".\n' + screen
        for path in ("start", "rotate", "kickoff"):
            with self.subTest(path=path):
                text = self.report(path, screens=screen)
                self.assert_update_message(text, path, "en", versions)
                self.assertNotIn("0.162.1", text)
                self.assertNotIn("0.165.0", text)
                self.assertNotIn("9.8.7", text)
                self.assertNotIn("9.8.8", text)

    def test_all_paths_use_version_neutral_fallback_when_screen_no_longer_supplies_versions(self):
        for path in ("start", "rotate", "kickoff"):
            for lang in ("en", "zh"):
                for screen in (None, "", READY, '"' + HEADING + '"\n' + OPTION):
                    with self.subTest(path=path, lang=lang, screen=screen):
                        text = self.report(path, lang, screens=screen, readiness="update")
                        self.assert_update_message(text, path, lang, versions=None)

    def test_existing_trust_and_timeout_messages_remain_verbatim(self):
        for lang in ("en", "zh"):
            for ready in ("trust", "timeout"):
                for path in ("start", "rotate", "kickoff"):
                    with self.subTest(lang=lang, ready=ready, path=path):
                        if path == "start":
                            expected = {
                                ("en", "trust"): "the agent asks whether to trust this folder: confirm in the session, then run chief.py kickoff codex-update",
                                ("zh", "trust"): "Agent 在问是否信任这个目录：进入会话确认后运行 chief.py kickoff codex-update",
                                ("en", "timeout"): "the agent was not ready within 120s: check the session, then run chief.py kickoff codex-update",
                                ("zh", "timeout"): "Agent 120 秒内没有就绪：进入会话查看后运行 chief.py kickoff codex-update",
                            }[(lang, ready)]
                        elif path == "rotate":
                            expected = ("the new session is not ready ({}): handle it in the session, then run chief.py nudge codex-update" if lang == "en" else
                                        "新会话没有就绪（{}）：进入会话处理后运行 chief.py nudge codex-update").format(ready)
                        else:
                            expected = ("error: the session is not ready (perhaps waiting for you to trust the folder); handle it in the session and retry" if lang == "en" else
                                        "错误：会话还没就绪（可能在等你确认信任目录），进入会话处理后再试")
                        self.assertEqual(self.report(path, lang, screens="", readiness=ready), expected)


class CodexUpdateDocumentationTests(unittest.TestCase):
    def test_readme_documents_menu_nonintervention_prefix_risk_and_recovery_commands(self):
        text = read_documentation()
        # A short contiguous paragraph/list must connect the policy and recovery;
        # unrelated mentions elsewhere in this large README cannot satisfy it.
        section = re.search(r"(?is)Codex[^\n]*(?:update menu|startup update)[\s\S]{0,1800}", text)
        self.assertIsNotNone(section, "document Codex's startup update menu")
        policy = " ".join(section.group(0).split())
        self.assertIn("Update available", policy)
        self.assertRegex(policy, r"(?i)Chief[^\n]*(?:never|does not|won't)[^\n]*(?:updat|upgrad)[^\n]*skip")
        self.assertIn("npm install -g @openai/codex", policy)
        self.assertRegex(policy, r"(?i)prefix")
        self.assertRegex(policy, r"(?i)(?:yourself|manually|user)")
        self.assertIn("Esc", policy)
        self.assertIn("chief.py kickoff <id>", policy)
        self.assertIn("chief.py nudge <id>", policy)


if __name__ == "__main__":
    unittest.main()
