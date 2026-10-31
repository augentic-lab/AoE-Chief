"""A working agent is not at its prompt, even when AoE briefly reports waiting.

Codex keeps "Ask Codex to do anything" on screen while it works. During the 2026-10-31 adopt end-to-end run, AoE
reported waiting mid-turn and Chief typed the adoption notice into the busy session. The screens below are real
captures (Codex 0.165.0).
"""
import json
import unittest
from unittest import mock

import chief

FOOTER = ("› Ask Codex to do anything\n"
          "  GPT-6.1-Sol xhigh · /tmp/e2e/calc · Context 1% used · weekly 91% left\n"
          "  ? for shortcuts\n")
CODEX_WORKING = ("• I’ll run the command and wait for it to finish.\n"
                 "• Working (6s • esc to interrupt) · 1 background terminal running · /ps to view · /stop to close\n"
                 + FOOTER)
CODEX_DONE = "• Ran sleep 40 && echo done\n  └ done\n• done\n  Worked for 43s • 20:23\n" + FOOTER
CLAUDE_WORKING = ("✻ Pondering… (12s · ↓ 300 tokens · esc to interrupt)\n"
                  "────────────────────────────────────────\n"
                  "❯ \n"
                  "────────────────────────────────────────\n"
                  "  ? for shortcuts\n")


class BusyScreenTests(unittest.TestCase):
    def test_working_codex_is_not_at_prompt_even_when_aoe_says_waiting(self):
        for status in ("idle", "waiting"):
            with self.subTest(status=status):
                self.assertFalse(chief.at_prompt(status, CODEX_WORKING))
                self.assertTrue(chief.at_prompt(status, CODEX_DONE))

    def test_working_claude_is_not_at_prompt(self):
        self.assertFalse(chief.at_prompt("waiting", CLAUDE_WORKING))
        self.assertTrue(chief.at_prompt("idle", CLAUDE_WORKING.replace(" · esc to interrupt", "").split("\n", 1)[1]))

    def test_single_observation_reports_a_working_session_as_not_ready(self):
        show = json.dumps({"status": "waiting"})
        with mock.patch.object(chief, "aoe", return_value=show), \
                mock.patch.object(chief, "screen", return_value=CODEX_WORKING):
            self.assertEqual(chief.wait_ready({}, "0123456789abcdef", False, timeout=0), "timeout")
        with mock.patch.object(chief, "aoe", return_value=show), \
                mock.patch.object(chief, "screen", return_value=CODEX_DONE):
            self.assertEqual(chief.wait_ready({}, "0123456789abcdef", False, timeout=0), "ready")


if __name__ == "__main__":
    unittest.main()
