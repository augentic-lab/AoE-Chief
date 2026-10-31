"""Acceptance contract for the restricted, asynchronous Inbox ':' command bar.

Drive real key dispatch/rendering and isolated CLI processes. The existing
navigation/composer/cleanup suites remain part of this acceptance contract.
"""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import threading
import time
from unittest import mock

import chief
import chief_tui as tui
import inbox_command_support as support
import test_inbox_composer as composer


class EntryAndParsingTests(support.CommandFixture):
    def test_colon_opens_one_line_with_shared_cheat_sheet_and_localized_help(self):
        for lang in ("en", "zh"):
            with self.subTest(lang=lang):
                chief.LANG = lang

                def inspect():
                    self.command_open()
                    rows = self.frame()
                    sheet = "\n".join(rows[-8:-2])
                    for command in support.CHIEF_COMMANDS + support.SESSION_COMMANDS:
                        self.assertIn(command, sheet)
                    self.assertIn("aoe", sheet)
                    self.assertIn("Tab", rows[-1])
                    self.assertIn("Esc", rows[-1])
                    self.assertRegex(rows[-1], r"↑|Up")
                    self.assertIn(":", rows[-2], "one command input line is immediately above the footer")
                    if lang == "zh":
                        self.assertRegex("\n".join(rows[-8:]), r"[\u4e00-\u9fff]")
                    for width, height in ((40, 10), (60, 16), (100, 30)):
                        rendered = tui.render(chief, self.app.st, width, height)
                        self.assertEqual(len(rendered), height)
                        self.assertTrue(all(tui.width("".join(t for t, _ in row)) == width
                                            for row in rendered))

                self.scenario(":", composer.Action(inspect), "\x1b")
                self.assertIsNone(self.app.st["input"])

    def test_bare_and_chief_prefixed_commands_use_the_existing_cli(self):
        task = self.task()
        for prefix in ("", "chief "):
            self.scenario(*self.command(prefix + "tasks"), self.completed(task["id"]),
                          *self.command(prefix + "show task-alpha --turns 7"),
                          self.completed(task["goal"]))
        self.assertTrue(self.calls())
        for row in self.calls():
            self.assertEqual(row["argv"][:2], ["-p", self.cfg["profile"]])
            self.assertFalse(row["tty"], "children may not read the curses terminal")
        for argv, kwargs in self.launches:
            self.assertIsInstance(argv, (list, tuple), "execute parsed argv, never command text")
            self.assertFalse(kwargs.get("shell", False), "the restricted bar never invokes a shell")

    def test_quoted_unicode_and_shell_looking_argument_values_remain_literal(self):
        goal = "Keep 雪, spaces, 'quotes', ; | > $HOME $(touch NEVER) `id` * ~ literal"
        args = ["new", "--repo", str(self.repo), "--name", "Quoted task", "--goal", goal,
                "--check", "python3 -m unittest discover -s tests", "--protected", "tests",
                "--rounds", "4", "--hours", "1.5", "--tool", "claude", "--branch", "chief/literal", "--base-branch",
                self.git(self.repo, "branch", "--show-current"), "--autonomy", "observe",
                "--no-test-first", "--id", "literal-task", "--draft"]
        self.scenario(*self.command("chief " + " ".join(map(shlex.quote, args))),
                      self.completed("literal-task"))
        task = chief.load_task("literal-task")
        self.assertEqual(task["goal"], goal)
        self.assertEqual(task["checks"], ["python3 -m unittest discover -s tests"])
        self.assertEqual(task["protected"], ["tests"])
        self.assertEqual(task["budget"], {"rounds": 4, "hours": 1.5})
        for name, value in (("tool", "claude"), ("branch", "chief/literal"), ("autonomy", "observe"), ("phase", "build")):
            self.assertEqual(task[name], value)
        self.assertFalse((self.repo / "NEVER").exists())
        self.assertFalse(any(args[0] == "add" for args in self.aoe_args()))

    def test_new_from_file_overrides_and_dry_run_keep_existing_cli_semantics(self):
        contract = self.root / "contract file's name.json"
        contract.write_text(json.dumps(dict(repo=str(self.repo), name="Original", goal="From JSON",
            checks=["old check"], protected=["old path"], budget={"rounds": 11, "hours": 2.0})))
        args = ["new", "--from", str(contract), "--id", "from-file", "--name", "Override",
                "--goal", "Overridden goal", "--check", "first check", "--check", "second check",
                "--protected", "tests", "--protected", "config", "--scope", "src",
                "--milestone", "First milestone", "--small", "naming", "--hours", "1.25",
                "--trust", "--draft"]
        self.scenario(*self.command(" ".join(map(shlex.quote, args))), self.completed("from-file"))
        task = chief.load_task("from-file")
        self.assertEqual(task["name"], "Override")
        self.assertEqual(task["goal"], "Overridden goal")
        self.assertEqual(task["checks"], ["first check", "second check"])
        self.assertEqual(task["protected"], ["tests", "config"])
        self.assertEqual(task["budget"], {"rounds": 11, "hours": 1.25})
        self.assertEqual(task["scope"], "src")
        self.assertEqual(task["milestones"], ["First milestone"])
        self.assertEqual(task["small_decisions"], ["naming"])
        self.assertIs(task["trust"], True)
        self.scenario(*self.command("new --from " + self.q(contract) + " --id dry-run-only --dry-run"),
                      self.completed(), composer.Action(lambda: self.assertIn("kickoff prompt",
                          "\n".join(self.frame(height=1000)[1:-2]))))
        self.assertEqual([t["id"] for t in chief.all_tasks()], ["from-file"])
        self.assertFalse(any(a[0] == "add" for a in self.aoe_args()))

    def test_decide_quoted_dismissal_uses_decision_id_and_existing_storage(self):
        self.decision()
        reason = "Already answered: 雪; keep | everything literal"
        self.scenario(*self.command("decide task-alpha:1 --dismiss " + self.q(reason)),
                      self.completed("task-alpha:1"))
        decision = chief.load_decisions("task-alpha")[0]
        self.assertEqual(decision["state"], "dismissed")
        self.assertEqual(decision["reason"], reason)
        self.assertFalse(any(a[0] == "send" for a in self.aoe_args()))

    def test_track_untrack_and_tick_keep_cli_arguments_and_profile(self):
        self.scenario(*self.command("track live-1111 live-2222"), self.completed("Tracking"))
        self.assertEqual(chief.config()["tracked_ids"], ["live-1111", "live-2222"])
        self.assertEqual(self.app.cfg["tracked_ids"], ["live-1111", "live-2222"])
        self.scenario(*self.command("chief untrack live-1111 live-2222"), self.completed("Untracked"))
        self.assertEqual(chief.config()["tracked_ids"], [])
        self.assertEqual(self.app.cfg["tracked_ids"], [])
        self.scenario(*self.command("tick --dry-run"), self.completed("nothing to do"))

    def test_blank_submission_and_escape_discard_input_without_running_it(self):
        for enter in ("\n", "\r", tui.curses.KEY_ENTER):
            self.scenario(*self.command("   ", submit=False), (enter,),
                          composer.Check(self.assert_idle), "\x1b")
        self.scenario(*self.command("close task-that-does-not-exist", submit=False), "\x1b",
                      composer.Action(lambda: self.assertIsNone(self.app.st["input"])),
                      ":", composer.Action(self.command_open), (tui.curses.KEY_UP,),
                      composer.Action(lambda: self.assert_buffer("")), "\x1b")
        self.assertFalse(chief.all_tasks())
        self.assertFalse(any(a[0] == "remove" or a[:2] in
                             (["session", "stop"], ["session", "archive"]) for a in self.aoe_args()))

    def test_nudge_preserves_guidance_and_does_not_use_a_shell(self):
        self.task()
        message = "Keep 雪 and spaces; no | shell > expansion $HOME"
        self.scenario(*self.command("nudge task-alpha " + self.q(message)),
                      self.completed("Sent", seconds=10))
        sends = [a for a in self.aoe_args() if a[0] == "send"]
        self.assertEqual(len(sends), 1)
        self.assertIn("Message from the user: " + message, sends[0][-1])
        self.assertEqual(chief.load_task("task-alpha")["nudges"][-1]["text"], message)

    def test_only_list_and_the_six_supported_aoe_session_operations_are_allowed(self):
        for command, expected in (("aoe list", None), ("aoe list --json", None),
                                  ("aoe session show live-1111", ["session", "show", "live-1111"]),
                                  ("aoe session start live-1111", ["session", "start", "live-1111"]),
                                  ("aoe session unarchive archived-3333", ["session", "unarchive", "archived-3333"]),
                                  ("aoe session restore trashed-4444", ["session", "restore", "trashed-4444"])):
            with self.subTest(command=command):
                self.scenario(*self.command(command), self.completed("live-1111" if expected is None else " ".join(expected)))
                if expected is not None:
                    self.assertIn(expected, self.aoe_args())

    def test_language_setting_reaches_the_background_chief_cli(self):
        chief.LANG = "zh"
        with mock.patch.dict(os.environ, {"AOE_CHIEF_LANG": "zh"}):
            self.scenario(*self.command("tasks"), self.completed("看板是空的"))

    def test_unsupported_or_malformed_input_is_rejected_before_any_execution(self):
        invalid = [
            "echo hello", "/bin/true", "python3 -c 'print(1)'", "bash -c id", "./chief.py tasks",
            "chief inbox", "chief console", "watch", "init", "sessions", "task live-1111",
            "review task-alpha", "rotate task-alpha", "kickoff task-alpha", "lang zh", "chief",
            "aoe", "aoe remove live-1111 --force", "aoe add /tmp", "aoe send live-1111 hello",
            "aoe session attach live-1111", "aoe session capture live-1111", "aoe session delete live-1111",
            "aoe session purge live-1111", "aoe session", "aoe session show", "aoe session start",
            "aoe session show live-1111 extra", "aoe -p other list", "aoe list --profile other",
            "tasks --unknown", "show", "show live-1111 --turns nope", "close", "clean --yes",
            "decide task-alpha:1 --accept --reply yes", "new --tool unsupported", "track",
            "tasks; tick", "tasks&&tick", "tasks || tick", "tasks | cat", "tasks &", "tasks\n tick",
            "tasks > output", "tasks 2>errors", "tasks < input", "tasks >> output", "tasks <<< hi",
            "tasks $(id)", "show ${HOME}", "show $HOME", "show `id`", "show ~", "show *",
            "nudge task-alpha 'unterminated", 'nudge task-alpha "unterminated', "show live-1111\\",
        ]
        real_popen = subprocess.Popen
        for command in invalid:
            with self.subTest(command=command):
                self.app = tui.Inbox(self.cfg, chief, 3600)
                launches = []

                def popen(argv, *args, **kwargs):
                    launches.append((argv, kwargs))
                    return real_popen(argv, *args, **kwargs)

                # A newline is normally a submit key, so insert the full buffer
                # directly for the multiline rejection case (e.g. recalled text).
                with mock.patch.object(subprocess, "Popen", side_effect=popen):
                    self.scenario(":", composer.Action(self.command_open),
                                  composer.Action(lambda: self.app.st["input"].update(buf=command)),
                                  "\n", composer.Check(self.assert_idle),
                                  composer.Action(lambda: self.assertRegex("\n".join(self.frame()).lower(),
                                      r"invalid|unsupported|not allowed|unknown|error|usage|required|forbidden|reject")), "\x1b")
                for argv, kwargs in launches:
                    self.assertIsInstance(argv, (list, tuple), "never pass command text to a shell")
                    self.assertFalse(kwargs.get("shell", False))
                    exe = str(argv[0])
                    if Path(exe).name == "git":
                        continue  # Existing refresh resolves repository roots.
                    if exe == str(self.aoe_executable) and any(
                            list(argv[3:3 + len(p)]) == p for p in (["list"], ["session", "list"], ["trash", "list"])):
                        continue  # Completion may load its read-only cache.
                    self.fail("invalid input launched a process: " + repr(argv))


class CompletionAndHistoryTests(support.CommandFixture):
    def test_tab_completes_supported_command_names_with_or_without_chief_prefix(self):
        for command in support.CHIEF_COMMANDS:
            for prefix in ("", "chief "):
                unique = next(command[:n] for n in range(1, len(command) + 1)
                              if sum(c.startswith(command[:n]) for c in support.CHIEF_COMMANDS) == 1)
                self.scenario(*self.command(prefix + unique, submit=False), "\t",
                              composer.Action(lambda expected=prefix + command: self.assert_buffer(expected)), "\x1b")
        for command in support.SESSION_COMMANDS:
            unique = next(command[:n] for n in range(1, len(command) + 1)
                          if sum(c.startswith(command[:n]) for c in support.SESSION_COMMANDS) == 1)
            self.scenario(*self.command("aoe session " + unique, submit=False), "\t",
                          composer.Action(lambda expected="aoe session " + command: self.assert_buffer(expected)), "\x1b")
        self.scenario(*self.command("aoe li", submit=False), "\t",
                      composer.Action(lambda: self.assert_buffer("aoe list")), "\x1b")

    def test_tab_uses_task_session_and_pending_decision_context_not_argument_values(self):
        self.task("task-alpha")
        self.task("task-beta", sid="live-2222")
        self.decision("task-alpha:7")
        self.decision("task-alpha:8", "sent")
        cases = [("show task-a", "show task-alpha"), ("chief nudge task-b", "chief nudge task-beta"),
                 ("close task-a", "close task-alpha"), ("track live-1", "track live-1111"),
                 ("track live-1111 live-2", "track live-1111 live-2222"),
                 ("show live-2", "show live-2222"), ("decide task-alpha:", "decide task-alpha:7"),
                 ("chief decide task-alpha:", "chief decide task-alpha:7")]
        # Seed the existing tracking cache for untrack's context.
        self.cfg["tracked_ids"] = ["live-1111", "live-2222"]
        chief.save_cfg(self.cfg)
        cases.append(("untrack live-2", "untrack live-2222"))
        for before, after in cases:
            with self.subTest(before=before):
                self.scenario(*self.command(before, submit=False), "\t",
                              self.completes(after), "\x1b")
        for literal in ('nudge task-alpha "task-b', "decide task-alpha:7 --reply task-b",
                        "new --name task-b", "show no-match"):
            self.scenario(*self.command(literal, submit=False), "\t",
                          composer.Action(lambda literal=literal: self.assert_buffer(literal)), "\x1b")

    def test_session_completion_includes_archives_and_trash_for_recovery_commands(self):
        for before, after in (("aoe session unarchive archived-", "aoe session unarchive archived-3333"),
                              ("aoe session restore trashed-", "aoe session restore trashed-4444"),
                              ("aoe session show archived-", "aoe session show archived-3333"),
                              ("aoe session start live-1", "aoe session start live-1111"),
                              ("aoe session stop live-1", "aoe session stop live-1111"),
                              ("aoe session archive live-2", "aoe session archive live-2222")):
            with self.subTest(before=before):
                self.scenario(*self.command(before, submit=False), "\t",
                              self.completes(after), "\x1b")

    def test_tab_never_waits_for_completion_io_and_cached_ids_remain_usable(self):
        self.task()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        real_call = chief.call

        def delayed(argv, *args, **kwargs):
            if str(argv[0]) == str(self.aoe_executable):
                entered.set()
                release.wait(2)
            return real_call(argv, *args, **kwargs)

        def tab():
            started = time.monotonic()
            self.app.typed("\t")
            self.assertLess(time.monotonic() - started, .25, "Tab must not perform blocking I/O")
            self.assert_buffer("close task-alpha")

        with mock.patch.object(chief, "call", side_effect=delayed):
            self.scenario(*self.command("close task-a", submit=False), composer.Action(tab), "\x1b",
                          composer.Action(lambda: self.assertIsNone(self.app.st["input"])),
                          composer.Action(release.set))

    def test_up_down_recall_submitted_commands_and_restore_the_unsubmitted_draft(self):
        self.scenario(*self.command("tasks"), self.completed("board is empty"),
                      *self.command("aoe session show live-1111"), self.completed("shown session live-1111"),
                      *self.command("unfinished text", submit=False), (tui.curses.KEY_UP,),
                      composer.Action(lambda: self.assert_buffer("aoe session show live-1111")),
                      (tui.curses.KEY_UP,), composer.Action(lambda: self.assert_buffer("tasks")),
                      (tui.curses.KEY_UP,), composer.Action(lambda: self.assert_buffer("tasks")),
                      (tui.curses.KEY_DOWN,), composer.Action(lambda: self.assert_buffer("aoe session show live-1111")),
                      (tui.curses.KEY_DOWN,), composer.Action(lambda: self.assert_buffer("unfinished text")),
                      "\x15", "tasks", "\x1b", ":", composer.Action(self.command_open),
                      (tui.curses.KEY_UP,), composer.Action(lambda: self.assert_buffer("aoe session show live-1111")), "\x1b")
        self.app = tui.Inbox(self.cfg, chief, 3600)
        self.scenario(":", composer.Action(self.command_open), (tui.curses.KEY_UP,),
                      composer.Action(lambda: self.assert_buffer("")), "\x1b")


class ConfirmationAndPromptTests(support.CommandFixture):
    def assert_confirmation(self):
        self.assertIsNotNone(self.app.st["confirm"], "destructive commands require explicit y/N")
        self.assertRegex(self.app.st["confirm"]["prompt"], r"[yY]/N|\[y/N\]")

    def test_destructive_commands_default_no_and_flags_cannot_skip_confirmation(self):
        self.task()
        commands = ["close task-alpha", "close task-alpha --abandon --remove-session --force",
                    "clean", "clean --branches", "clean --dry-run",
                    "aoe session stop live-1111", "aoe session archive live-1111"]
        for command in commands:
            for decline in ("\n", "\r", "n", "\x1b", tui.curses.KEY_ENTER):
                with self.subTest(command=command, decline=decline):
                    before = len(self.aoe_args())
                    self.scenario(*self.command(command), composer.Action(self.assert_confirmation),
                                  (decline,), composer.Check(self.assert_idle))
                    mutations = [a for a in self.aoe_args()[before:] if a[0] == "remove"
                                 or a[:2] in (["session", "stop"], ["session", "archive"])]
                    self.assertEqual(mutations, [])
                    self.assertEqual(chief.load_task("task-alpha")["state"], "running")
                    self.assertIsNone(self.app.st["confirm"])

    def test_yes_submits_close_stop_and_archive_only_once(self):
        for command, operation in (("close task-alpha", ["session", "archive", "live-1111"]),
                                   ("aoe session stop live-2222", ["session", "stop", "live-2222"]),
                                   ("aoe session archive live-2222", ["session", "archive", "live-2222"])):
            with self.subTest(command=command):
                self.task()
                before = self.aoe_args().count(operation)
                self.scenario(*self.command(command), composer.Action(self.assert_confirmation),
                              "y\n\r", (tui.curses.KEY_ENTER,), composer.Check(self.assert_idle), "\x1b")
                self.assertEqual(self.aoe_args().count(operation) - before, 1)
                if command.startswith("close"):
                    task = chief.load_task("task-alpha")
                    self.assertEqual(task["state"], "done")
                    self.assertTrue(task["session_archived"])
                    self.assertFalse(task.get("session_removed", False))

    def cleanup_candidate(self):
        wt = self.root / "worktree-clean"
        self.git(self.repo, "worktree", "add", "-q", "-b", "chief/cleanup", str(wt))
        progress = wt / ".chief" / "progress.md"
        progress.parent.mkdir()
        progress.write_text("Keep this cleanup progress.\n")
        task = self.task("cleanup", "done", "archived-3333", worktree=str(wt), branch="chief/cleanup")
        self.records[2]["project_path"] = str(wt)
        self.write_records()
        return task, wt

    def advance_to_candidates(self):
        self.assert_confirmation()
        # Implementations may combine the initial guard with the candidate
        # prompt or retain two confirmations; candidates must be reviewed.
        if not re.search(r"candidate|listed|these|above", self.app.st["confirm"]["prompt"], re.I):
            self.app.answered("y")

    def candidates_visible(self):
        self.assert_confirmation()
        self.assertIn("cleanup", self.detail())
        self.assertIn("chief/cleanup", self.detail())
        self.assertRegex(self.detail().lower(), r"clean|candidate")
        self.assertRegex(self.app.st["confirm"]["prompt"].lower(), r"candidate|listed|these|above")

    def test_clean_routes_candidate_confirmation_through_inbox_and_preserves_progress(self):
        task, wt = self.cleanup_candidate()
        self.scenario(*self.command("clean"), composer.Check(self.assert_confirmation),
                      composer.Action(self.advance_to_candidates), composer.Check(self.candidates_visible), "n",
                      composer.Check(self.assert_idle))
        self.assertTrue(wt.exists())
        self.assertFalse(chief.load_task(task["id"]).get("session_removed"))
        self.scenario(*self.command("clean"), composer.Check(self.assert_confirmation),
                      composer.Action(self.advance_to_candidates), composer.Check(self.candidates_visible), "y",
                      self.completed("session/worktree moved to AoE trash"))
        self.assertEqual((chief.TASKS / task["id"] / "progress.md").read_text(), "Keep this cleanup progress.\n")
        self.assertTrue(chief.load_task(task["id"])["session_removed"])
        self.assertFalse(wt.exists())
        self.assertTrue(self.git(self.repo, "rev-parse", "--verify", task["branch"]))

    def test_clean_retains_trash_disabled_and_dirty_worktree_safeguards(self):
        _, wt = self.cleanup_candidate()
        self.control["trash"] = False
        self.write_control()
        self.scenario(*self.command("clean"), composer.Check(self.assert_confirmation),
                      composer.Action(self.advance_to_candidates), composer.Check(self.candidates_visible), "y",
                      self.completed("trash is disabled"))
        self.assertTrue(wt.exists())
        self.assertFalse(any(a[0] == "remove" for a in self.aoe_args()))
        (wt / "uncommitted.txt").write_text("retain me")
        self.scenario(*self.command("clean"), composer.Check(self.assert_confirmation), "y",
                      self.completed("Skip: worktree is dirty"))
        self.assertTrue((wt / "uncommitted.txt").exists())
        self.assertFalse(any(a[0] == "remove" for a in self.aoe_args()))

    def assert_contract_preview(self, intent):
        self.assertFalse(chief.all_tasks(), "preview must not save or start the task")
        self.assertIn(intent, self.detail())
        self.assertIn(str(self.repo), self.detail())
        self.assertRegex("\n".join(self.frame()), r"Enter|[Ee]nter|回车")
        self.assertRegex("\n".join(self.frame()), r"Esc")

    def test_new_intent_contract_requires_inbox_approval_and_escape_does_not_create(self):
        intent = "Import quoted 雪 receipts"
        command = "new " + self.q(intent) + " --repo " + self.q(self.repo) + " --draft --id proposed"
        for decline in ("\x1b", "n"):
            self.scenario(*self.command(command), composer.Check(lambda: self.assert_contract_preview(intent)),
                          decline, composer.Check(self.assert_idle))
            self.assertFalse(chief.all_tasks())
        self.scenario(*self.command(command), composer.Check(lambda: self.assert_contract_preview(intent)),
                      "\n\n", self.completed("proposed"))
        self.assertEqual(len(chief.all_tasks()), 1)
        self.assertEqual(chief.load_task("proposed")["goal"], intent)
        self.assertIs(chief.load_task("proposed")["test_first"], True)
        self.assertEqual(chief.load_task("proposed")["phase"], "test")

    def test_new_contract_edit_remains_reviewable_before_inbox_approval(self):
        editor = self.executable("contract editor's fixture", r'''
import json, pathlib, sys
path = pathlib.Path(sys.argv[-1])
contract = json.loads(path.read_text())
contract.update(name="Edited contract", goal="Edited goal", checks=["edited check"])
path.write_text(json.dumps(contract))
''')

        def edited_preview():
            self.assertFalse(chief.all_tasks())
            for value in ("Edited contract", "Edited goal", "edited check"):
                self.assertIn(value, self.detail())

        with mock.patch.dict(os.environ, {"EDITOR": self.q(editor)}):
            self.scenario(*self.command("new 'Original intent' --repo " + self.q(self.repo) +
                                        " --draft --id edited-task"),
                          composer.Check(lambda: self.assert_contract_preview("Original intent")),
                          "e", composer.Check(edited_preview), "\n", self.completed("edited-task"))
        task = chief.load_task("edited-task")
        self.assertEqual(task["name"], "Edited contract")
        self.assertEqual(task["goal"], "Edited goal")
        self.assertEqual(task["checks"], ["edited check"])

    def test_new_yes_and_explicit_contract_flags_keep_existing_cli_behavior(self):
        command = "new 'Explicit intent' --repo " + self.q(self.repo) + " --yes --draft --id accepted"
        self.scenario(*self.command(command), self.completed("accepted"))
        self.assertEqual(chief.load_task("accepted")["phase"], "test")


class BackgroundAndCancellationTests(support.CommandFixture):
    def test_stdout_stderr_and_exit_status_stream_into_detail_without_blocking_navigation(self):
        self.selected_items()
        rule = self.gated(["session", "show", "slow"], stdout="stdout before gate\n",
                          stderr="stderr before gate\n", late="stdout after gate\n", code=7)

        def streaming():
            self.assert_started(rule)
            self.assertIn("stdout before gate", self.detail())
            self.assertIn("stderr before gate", self.detail())

        self.scenario(*self.command("aoe session show slow"), composer.Check(streaming),
                      "j", composer.Action(lambda: self.assertEqual(self.app.selected()["sid"], "live-2222")),
                      "k", composer.Action(lambda: self.assertEqual(self.app.selected()["sid"], "live-1111")),
                      "\n\r", (tui.curses.KEY_ENTER,),
                      composer.Action(lambda: Path(rule["release"]).touch()),
                      composer.Check(self.assert_idle),
                      composer.Action(lambda: self.assertIn(chief.load_task("task-alpha")["goal"], self.detail())),
                      composer.Action(lambda: self.assertNotRegex(self.detail(), r"stdout (?:before|after) gate|stderr before gate")),
                      "L", self.completed("stdout before gate", "stderr before gate", "stdout after gate"),
                      composer.Action(lambda: self.assertRegex(self.detail().lower(), r"(?:exit|status|code|failed).*7")))
        self.assertEqual(self.aoe_args().count(rule["argv"]), 1)

    def test_output_is_scrollable_and_survives_refresh_and_selection_changes(self):
        self.selected_items()
        self.items[0]["log"]["last_reply"] = "SELECTED_COMMAND_TASK_DETAILS"
        self.items[1]["log"]["last_reply"] = "SELECTED_COMMAND_SESSION_DETAILS"
        self.control["rules"].append(dict(argv=["session", "show", "long"],
            stdout="\n".join("output-line-{:03d}".format(n) for n in range(90)) + "\n"))
        self.write_control()
        seen = set()
        expected = {"output-line-{:03d}".format(n) for n in range(90)}

        def capture():
            seen.update(re.findall(r"output-line-\d{3}", self.detail()))

        def selected_details(sid, marker):
            self.assertEqual(self.app.selected()["sid"], sid)
            self.assertIn(marker, self.detail(), "selection restores the item's details")
            self.assertNotRegex(self.detail(), r"output-line-\d{3}", "old output is reachable through L")

        scroll = []
        for key in (tui.curses.KEY_PPAGE,) * 20 + (tui.curses.KEY_NPAGE,) * 20:
            scroll.extend([(key,), composer.Action(capture)])
        self.scenario(*self.command("aoe session show long"), composer.Check(self.assert_idle),
                      *scroll, composer.Action(lambda: self.assertEqual(seen, expected)),
                      composer.Action(seen.clear), "g", composer.Check(self.assert_idle),
                      "j", composer.Action(lambda: selected_details("live-2222", "SELECTED_COMMAND_SESSION_DETAILS")),
                      "k", composer.Action(lambda: selected_details("live-1111", "SELECTED_COMMAND_TASK_DETAILS")),
                      "g", composer.Check(self.assert_idle),
                      composer.Action(lambda: selected_details("live-1111", "SELECTED_COMMAND_TASK_DETAILS")),
                      "L", *scroll, "\x1b",
                      composer.Action(lambda: selected_details("live-1111", "SELECTED_COMMAND_TASK_DETAILS")))
        self.assertEqual(seen, expected)

    def test_escape_cancels_owned_process_discards_late_results_and_allows_a_new_command(self):
        effect = self.root / "late-side-effect"
        rule = self.gated(["session", "show", "cancel-me"], effect=str(effect), late="STALE-CANCELLED-OUTPUT\n")

        def dead():
            self.assert_idle()
            self.assert_process_dead(int(Path(rule["started"]).read_text()))
            self.assertRegex("\n".join(self.frame()).lower(), r"cancel|terminat")

        self.scenario(*self.command("aoe session show cancel-me"),
                      composer.Check(lambda: self.assert_started(rule)), "\x1b", composer.Check(dead),
                      *self.command("tasks"), self.completed("board is empty"),
                      composer.Action(lambda: Path(rule["release"]).touch()), "g", composer.Check(self.assert_idle),
                      composer.Action(lambda: self.assertNotIn("STALE-CANCELLED-OUTPUT", self.detail())))
        self.assertFalse(effect.exists(), "a cancelled owned process may not resume to perform later work")

    def test_cancelling_chief_terminates_its_execution_process_and_aoe_descendant(self):
        self.task()
        rule = self.gated(["session", "capture", "--json", "--strip-ansi", "--lines", "40", "live-1111"])
        owned = {}

        def started():
            self.assert_started(rule)
            row = next(row for row in self.calls() if row["argv"][2:] == rule["argv"])
            owned.update(worker=row["ppid"], aoe=row["pid"])
            self.assertNotEqual(owned["worker"], os.getpid(), "Chief commands need an owned execution process")

        def stopped():
            self.assert_idle()
            self.assert_process_dead(owned["worker"])
            self.assert_process_dead(owned["aoe"])

        self.scenario(*self.command("show task-alpha"), composer.Check(started),
                      "\x1b", composer.Check(stopped), *self.command("tasks"), self.completed("task-alpha"))

    def test_cancel_does_not_claim_to_undo_completed_side_effects(self):
        self.task()
        effect = self.root / "completed-before-cancel"
        rule = self.gated(["session", "show", "after-side-effect"], early_effect=str(effect))
        self.scenario(*self.command("close task-alpha"),
                      composer.Check(lambda: self.assertIsNotNone(self.app.st["confirm"])), "y",
                      composer.Check(self.assert_idle), "\x1b",
                      *self.command("aoe session show after-side-effect"),
                      composer.Check(lambda: self.assertTrue(effect.exists())), "\x1b", composer.Check(self.assert_idle))
        self.assertEqual(chief.load_task("task-alpha")["state"], "done")
        self.assertEqual(effect.read_text(), "completed before cancellation")
        text = "\n".join(self.frame()).lower()
        self.assertNotRegex(text, r"(?:undone|rolled back|reverted|nothing changed|no changes made)")
        self.assertRegex(text, r"side effects|already|completed|not undone|not roll|may have|partial")

    def test_launch_error_is_visible_and_a_later_command_still_runs(self):
        missing = self.root / "missing AoE executable"
        with mock.patch.dict(os.environ, {"AOE_BIN": str(missing)}):
            self.scenario(*self.command("aoe session show live-1111"),
                          composer.Check(lambda: self.assertRegex(self.detail().lower(), r"failed|error|could not|no such file")))
        self.scenario(*self.command("tasks"), self.completed("board is empty"))

    def test_existing_refresh_navigation_reply_and_delegation_composer_still_work(self):
        self.selected_items()
        with mock.patch.object(chief, "reply_session", return_value=True) as reply:
            self.scenario(*self.command("tasks"), self.completed("task-alpha"),
                          "j", "r", "Literal reply 雪", "\n", composer.Check(self.assert_idle),
                          "g", composer.Check(self.assert_idle),
                          "N", composer.Check(lambda: self.assert_fields("", self.repo)), "\x1b")
        reply.assert_called_once_with(self.cfg, "live-2222", "Literal reply 雪")
        self.draft.assert_not_called()
        self.start.assert_not_called()


class HalfWidthTests(support.CommandFixture):
    """Usability at half of 80/120/160 columns, allowing for a tmux divider."""

    def narrow_screen(self):
        height, width = self.scr.getmaxyx()
        rows = tui.render(chief, self.app.st, width, height)
        self.assertEqual(len(rows), height)
        lines = ["".join(text for text, _ in row) for row in rows]
        self.assertTrue(all(tui.width(line) == width for line in lines))
        return lines

    def test_navigation_reply_and_refresh_remain_usable_at_half_width_in_both_languages(self):
        self.selected_items()
        with mock.patch.object(chief, "reply_session", return_value=True) as reply:
            for lang in ("en", "zh"):
                for width in (39, 59, 79):
                    with self.subTest(lang=lang, width=width):
                        chief.LANG = lang
                        self.scr.getmaxyx.return_value = (28, width)
                        self.app = tui.Inbox(self.cfg, chief, 3600)

                        def inspect_input():
                            self.assertEqual(self.app.selected()["sid"], "live-2222")
                            self.assertIn("Ready 雪", self.narrow_screen()[-2])

                        self.scenario(composer.Action(self.narrow_screen), "j", "r", "Ready 雪",
                                      composer.Action(inspect_input), "\n", composer.Check(self.assert_idle),
                                      "g", composer.Check(self.assert_idle), "k",
                                      composer.Action(lambda: self.assertEqual(self.app.selected()["sid"], "live-1111")),
                                      composer.Action(self.narrow_screen))
            self.assertEqual(reply.call_count, 6)
            self.assertTrue(all(call[0] == (self.cfg, "live-2222", "Ready 雪")
                                for call in reply.call_args_list))

    def test_command_editing_completion_history_and_output_fit_half_width(self):
        self.task()
        draft = "nudge task-alpha " + self.q("Long guidance " * 8 + "visible-tail 雪")
        for width in (39, 59, 79):
            with self.subTest(width=width):
                self.scr.getmaxyx.return_value = (28, width)
                self.app = tui.Inbox(self.cfg, chief, 3600)

                def command_visible():
                    self.assert_buffer("close task-alpha")
                    lines = self.narrow_screen()
                    self.assertIn("task-alpha", lines[-2])
                    self.assertIn("Tab", lines[-1])
                    self.assertIn("Esc", lines[-1])

                def output_visible():
                    self.assert_idle()
                    self.assertIn("task-alpha", "\n".join(self.narrow_screen()[1:-2]))

                self.scenario(*self.command("close task-a", submit=False), "\t",
                              self.completes("close task-alpha"), composer.Action(command_visible), "\x1b",
                              *self.command("tasks"), composer.Check(output_visible),
                              *self.command(draft, submit=False),
                              composer.Action(lambda: self.assertIn("visible-tail 雪", self.narrow_screen()[-2])),
                              (tui.curses.KEY_UP,), composer.Action(lambda: self.assert_buffer("tasks")),
                              (tui.curses.KEY_DOWN,), composer.Action(lambda: self.assert_buffer(draft)), "\x1b")

    def test_delegation_composer_keeps_both_fields_editable_at_half_width(self):
        for lang in ("en", "zh"):
            for width in (39, 59, 79):
                with self.subTest(lang=lang, width=width):
                    chief.LANG = lang
                    self.scr.getmaxyx.return_value = (28, width)
                    self.app = tui.Inbox(self.cfg, chief, 3600)

                    def fields_visible():
                        lines = self.narrow_screen()
                        self.assertIn("Import 雪", lines[-3])
                        self.assertRegex(lines[-3], r"intent|任务意图")
                        self.assertRegex(lines[-2], r"Repository|仓库")

                    self.scenario("N", "Import 雪", composer.Action(fields_visible),
                                  (tui.curses.KEY_DOWN,), "\x15", str(self.repo),
                                  composer.Action(fields_visible), (tui.curses.KEY_UP,), "\x1b",
                                  composer.Action(self.narrow_screen))
        self.assertFalse(chief.all_tasks())
        self.draft.assert_not_called()
        self.start.assert_not_called()

    def test_destructive_confirmation_and_scrollable_output_are_usable_at_half_width(self):
        self.selected_items()
        self.control["rules"].append(dict(argv=["session", "show", "narrow"],
            stdout="\n".join("row{:02d} ".format(n) + "readable wrapped output 雪 " * 3
                             for n in range(30)) + "\n"))
        self.write_control()
        for width in (39, 59, 79):
            with self.subTest(width=width):
                self.scr.getmaxyx.return_value = (28, width)
                self.app = tui.Inbox(self.cfg, chief, 3600)
                seen = set()

                def confirmation_visible():
                    self.assertIsNotNone(self.app.st["confirm"])
                    screen = "\n".join(self.narrow_screen())
                    self.assertIn("task-alpha", screen)
                    self.assertRegex(screen, r"[yY]/N")

                def capture():
                    seen.update(re.findall(r"row\d{2}", "\n".join(self.narrow_screen()[1:-2])))

                scroll = []
                for key in (tui.curses.KEY_PPAGE,) * 24 + (tui.curses.KEY_NPAGE,) * 24:
                    scroll.extend([(key,), composer.Action(capture)])
                self.scenario(*self.command("close task-alpha --force"),
                              composer.Action(confirmation_visible), "\n", composer.Check(self.assert_idle),
                              *self.command("aoe session show narrow"), composer.Check(self.assert_idle), *scroll)
                self.assertEqual(chief.load_task("task-alpha")["state"], "running")
                self.assertEqual(seen, {"row{:02d}".format(n) for n in range(30)})
