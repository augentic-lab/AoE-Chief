"""A task's model/effort never reaches a terminal worker (AoE forwards them only to ACP sessions), so `new` refuses them.

Verified 2026-10-31: `aoe add --tool claude --model opus` launched `claude --session-id ...` without --model.
"""
import unittest
from unittest import mock

import chief


class TaskModelRefusedTests(unittest.TestCase):
    def test_model_and_effort_are_refused_before_any_git_or_session_work(self):
        for key in ("model", "effort"):
            with self.subTest(key=key), mock.patch.object(chief, "call") as call:
                with self.assertRaisesRegex(RuntimeError, "--" + key):
                    chief.prepare_new_task({"repo": "/nonexistent", "name": "n", "goal": "g", key: "x"})
                call.assert_not_called()

    def test_empty_values_are_ignored(self):
        with mock.patch.object(chief, "call", return_value="/repo\n"), \
                mock.patch.object(chief, "TASKS", chief.Path("/nonexistent-chief-tasks")):
            t = chief.prepare_new_task({"repo": "/repo", "name": "n", "goal": "g", "model": "", "effort": None})
        self.assertEqual(t["repo"], "/repo")

    def test_add_command_never_passes_model_flags_for_a_new_task(self):
        with mock.patch.object(chief, "call", return_value="/repo\n"), \
                mock.patch.object(chief, "TASKS", chief.Path("/nonexistent-chief-tasks")):
            t = chief.prepare_new_task({"repo": "/repo", "name": "n", "goal": "g"})
        cmd = chief.add_command({"profile": "main"}, t, dry_run=True)
        self.assertNotIn("--model", cmd)
        self.assertNotIn("--effort", cmd)


if __name__ == "__main__":
    unittest.main()
