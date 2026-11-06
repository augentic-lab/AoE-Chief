"""Per-task worker launch commands, without real git, tmux, AoE or AI processes.

Exercise the CLI, persisted contracts, both worker launch paths and Chief's AI
launcher. A private Chief module and temporary homes keep the fixtures isolated.
"""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "chief.py"
INVALID_STRINGS = (
    "", " ", "claude --model glm-5.3", " claude-mix", "claude-mix ",
    "claude\tmix", "claude\nmix", "claude\rmix", "claude\u00a0mix",
    "/usr/local/bin/claude-mix", "./claude-mix", "bin/claude-mix",
    "~/bin/claude-mix", "bin\\claude-mix",
)


class TaskCommandFixture(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.home = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="chief-task-command-")))
        stack.enter_context(mock.patch.dict(os.environ, {
            "HOME": str(self.home), "AOE_CHIEF_HOME": str(self.home / "state"),
            "AOE_HOME": str(self.home / "aoe"), "AOE_CHIEF_LANG": "en",
            "CODEX_HOME": str(self.home / "codex"),
            "CLAUDE_CONFIG_DIR": str(self.home / "claude"),
        }))
        stack.enter_context(mock.patch.object(Path, "home", return_value=self.home))
        spec = importlib.util.spec_from_file_location("chief_task_command_acceptance", SOURCE)
        self.ch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ch)
        # Any missed external boundary is a test error, never a real process.
        for name in ("run", "Popen"):
            stack.enter_context(mock.patch.object(
                self.ch.subprocess, name, side_effect=AssertionError("unexpected external process")))
        self.repo = self.home / "repo"
        self.repo.mkdir()
        self.worktree = self.home / "worktree"
        self.worktree.mkdir()
        self.cfg = {"profile": "test", "tracked_ids": [], "tasks": {},
                    "commands": {"claude": "claude-chief", "codex": "codex-chief"}}
        self.ch.save_cfg(self.cfg)
        self.records = {}
        self.launches = []
        self.call = stack.enter_context(mock.patch.object(self.ch, "call", side_effect=self.fake_call))
        stack.enter_context(mock.patch.object(self.ch, "aoe_bin", return_value="aoe-fixture"))
        stack.enter_context(mock.patch.object(self.ch, "aoe_records", return_value=self.records))
        self.prepare_worktree = stack.enter_context(mock.patch.object(self.ch, "prepare_worktree"))
        self.ready = stack.enter_context(mock.patch.object(self.ch, "wait_ready", return_value="ready"))
        self.deliver = stack.enter_context(mock.patch.object(self.ch, "deliver", return_value=True))
        stack.enter_context(mock.patch.object(self.ch.shutil, "which",
                                             side_effect=lambda name: "/synthetic/bin/" + name))

    def contract(self, **fields):
        return dict({"repo": str(self.repo), "id": "launch-task", "name": "Launch task",
                     "goal": "Use the selected worker launcher", "tool": "claude",
                     "checks": ["python3 -m unittest discover -s tests"], "protected": ["tests"]},
                    **fields)

    def write_contract(self, contract):
        path = self.home / "contract.json"
        path.write_text(json.dumps(contract), encoding="utf-8")
        return str(path)

    def fake_call(self, argv, **kwargs):
        if argv[0] == "git":
            operation = argv[3:]
            if operation == ["rev-parse", "--show-toplevel"]:
                return str(self.repo) + "\n"
            if operation == ["rev-parse", "HEAD"]:
                return "b" * 40 + "\n"
            if operation[:3] == ["branch", "--list", "--"]:
                return "  " + operation[3] + "\n"
        elif argv[:4] == ["aoe-fixture", "-p", "test", "add"]:
            self.launches.append(list(argv))
            sid = "{:016x}".format(len(self.launches))
            self.records[sid] = {"id": sid, "project_path": str(self.worktree),
                                 "tool": argv[argv.index("--tool") + 1], "status": "idle"}
            return "ID: {}\nPath: {}\n".format(sid, self.worktree)
        elif argv[:5] == ["aoe-fixture", "-p", "test", "session", "stop"]:
            return ""
        elif argv[0] in ("/synthetic/bin/claude-chief", "/synthetic/bin/codex-chief"):
            return "Synthetic AI answer\n"
        raise AssertionError("unexpected command: {!r}".format(argv))

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = self.ch.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def new(self, contract=None, *flags):
        path = self.write_contract(self.contract() if contract is None else contract)
        code, out, err = self.cli("new", "--from", path, *flags)
        self.assertEqual(code, 0, out + err)
        return self.ch.load_task("launch-task")

    def rotate(self, task):
        self.ch.rotate_task(self.cfg, task, {"log": {"turns_total": 3}}, "context limit")
        return self.ch.load_task(task["id"])

    def assert_override(self, argv, command):
        self.assertEqual(argv.count("--cmd-override"), 1, argv)
        self.assertEqual(argv[argv.index("--cmd-override") + 1], command, argv)
        self.assertNotIn("--model", argv)
        self.assertNotIn("--effort", argv)

    def assert_invalid_message(self, message):
        message = message.lower()
        self.assertIn("command", message)
        self.assertRegex(message, r"bare|single.?token")
        self.assertRegex(message, r"session.?id|session id|tracking|track.*session")


class WorkerLaunchCommandTests(TaskCommandFixture):
    def test_json_command_is_persisted_and_reaches_new_worker_argv(self):
        task = self.new(self.contract(command="claude-mix"))
        self.assertEqual(task["command"], "claude-mix")
        self.assertEqual(task["state"], "running")
        self.assertEqual(len(self.launches), 1)
        self.assert_override(self.launches[0], "claude-mix")

    def test_cli_command_without_json_launches_worker(self):
        code, out, err = self.cli("new", "--repo", str(self.repo), "--name", "Launch task",
                                  "--goal", "Use GLM", "--tool", "claude", "--command", "claude-mix")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.ch.load_task("launch-task")["command"], "claude-mix")
        self.assertEqual(len(self.launches), 1)
        self.assert_override(self.launches[0], "claude-mix")

    def test_cli_command_overrides_json_field(self):
        task = self.new(self.contract(command="claude-other"), "--command", "claude-mix")
        self.assertEqual(task["command"], "claude-mix")
        self.assert_override(self.launches[0], "claude-mix")

    def test_rotation_reuses_persisted_task_command_across_successors(self):
        task = self.new(self.contract(command="claude-mix"))
        self.cfg["commands"]["claude"] = "claude-different-default"
        for _ in range(2):
            task = self.rotate(task)
            self.assertEqual(task["command"], "claude-mix")
            self.assertEqual(task["state"], "running")
            self.assert_override(self.launches[-1], "claude-mix")
            self.assertEqual(self.launches[-1][4], str(self.worktree))
        self.assertEqual(len(task["past_sessions"]), 2)

    def test_absent_command_keeps_config_launcher_for_new_and_rotation(self):
        task = self.new()
        self.assertNotIn("command", task)
        self.assert_override(self.launches[-1], "claude-chief")
        self.rotate(task)
        self.assert_override(self.launches[-1], "claude-chief")

    def test_absent_task_and_config_commands_keep_aoe_default(self):
        self.cfg.pop("commands")
        self.ch.save_cfg(self.cfg)
        task = self.new()
        self.rotate(task)
        self.assertEqual(len(self.launches), 2)
        for argv in self.launches:
            self.assertNotIn("--cmd-override", argv)

    def test_task_command_works_without_a_config_launcher(self):
        self.cfg.pop("commands")
        self.ch.save_cfg(self.cfg)
        task = self.new(self.contract(command="claude-mix"))
        self.rotate(task)
        for argv in self.launches:
            self.assert_override(argv, "claude-mix")

    def test_override_is_per_task_and_does_not_mutate_config(self):
        before = copy.deepcopy(self.cfg)
        task = self.new(self.contract(command="claude-mix"))
        self.rotate(task)
        other = self.contract(id="ordinary-task")
        prepared = self.ch.prepare_new_task(other)
        self.ch.create_task(self.cfg, prepared)
        self.assert_override(self.launches[-1], "claude-chief")
        self.assertEqual(self.cfg, before)
        self.assertEqual(self.ch.config(), before)

    def test_launch_command_applies_to_each_supported_worker_tool(self):
        for tool, command in (("claude", "claude-mix"), ("codex", "codex-wrapper"),
                              ("antigravity", "agy-wrapper")):
            with self.subTest(tool=tool):
                task = self.ch.prepare_new_task(self.contract(tool=tool, command=command))
                self.assert_override(self.ch.add_command(self.cfg, task, dry_run=True), command)

    def test_chief_ai_calls_keep_config_commands_after_task_launch_and_rotation(self):
        task = self.new(self.contract(command="claude-mix"))
        self.rotate(task)
        for engine in ("claude", "codex"):
            for read_files in (False, True):
                with self.subTest(engine=engine, read_files=read_files):
                    spec = self.ch.pick_model(self.ch.config(), engine, 2)
                    self.assertEqual(spec["command"], engine + "-chief")
                    self.call.reset_mock()
                    result = self.ch.generate_ai("Synthetic brief or review", engine, spec,
                                                 read_files=read_files)
                    self.assertEqual(result, "Synthetic AI answer\n")
                    self.call.assert_called_once()
                    argv = self.call.call_args[0][0]
                    self.assertEqual(argv[0], "/synthetic/bin/" + engine + "-chief")
                    self.assertNotIn("claude-mix", argv)


class CommandDisplayTests(TaskCommandFixture):
    def test_dry_run_displays_json_command_and_effective_aoe_argv(self):
        self.check_dry_run(self.contract(command="claude-mix"))

    def test_dry_run_displays_cli_override_of_json_command(self):
        self.check_dry_run(self.contract(command="claude-other"), "--command", "claude-mix")

    def check_dry_run(self, contract, *flags):
        before = self.ch.CFG.read_bytes()
        code, out, err = self.cli("new", "--from", self.write_contract(contract), *flags, "--dry-run")
        self.assertEqual(code, 0, out + err)
        displayed, offset = json.JSONDecoder().raw_decode(out)
        self.assertEqual(displayed["command"], "claude-mix")
        command_line = next(line for line in out[offset:].splitlines() if "--cmd-override" in line)
        self.assert_override(shlex.split(command_line.split("---- ", 1)[-1]), "claude-mix")
        self.assertEqual(self.launches, [])
        self.ready.assert_not_called()
        self.deliver.assert_not_called()
        self.prepare_worktree.assert_not_called()
        self.assertFalse(self.ch.TASKS.exists())
        self.assertEqual(self.ch.CFG.read_bytes(), before)
        for args, _ in self.call.call_args_list:
            self.assertEqual(args[0][0], "git")
            self.assertEqual(args[0][3:], ["rev-parse", "--show-toplevel"])

    def test_show_displays_persisted_task_command(self):
        task = self.new(self.contract(command="claude-mix"))
        with mock.patch.object(self.ch, "scope_info", return_value=None), \
                mock.patch.object(self.ch, "git_info", return_value=None), \
                mock.patch.object(self.ch, "recent_turns", return_value=[]), \
                mock.patch.object(self.ch, "screen", return_value=""):
            code, out, err = self.cli("show", task["id"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("claude-mix", out)
        self.assertRegex(out.lower(), r"command|launcher|launch command")


class CommandValidationTests(TaskCommandFixture):
    def test_invalid_contract_values_are_refused_before_git_or_session_work(self):
        for command in INVALID_STRINGS + (None, False, 17, [], {}):
            with self.subTest(command=command):
                self.call.reset_mock()
                with self.assertRaises((RuntimeError, ValueError)) as error:
                    self.ch.prepare_new_task(self.contract(command=command))
                self.assert_invalid_message(str(error.exception))
                self.call.assert_not_called()
                self.assertFalse(self.ch.TASKS.exists())
        self.ready.assert_not_called()
        self.deliver.assert_not_called()
        self.prepare_worktree.assert_not_called()

    def test_cli_rejects_invalid_json_and_flag_values_before_git_or_sessions(self):
        # Keep subcases independent even when the missing validation lets a
        # contract reach creation. The actual launch paths are exercised above.
        launched = dict(self.contract(), state="running", session_id="a" * 16,
                        worktree=str(self.worktree))
        with mock.patch.object(self.ch, "create_task", return_value=launched) as create:
            for source in ("json", "flag"):
                for command in INVALID_STRINGS:
                    with self.subTest(source=source, command=command):
                        contract = self.contract(**({"command": command} if source == "json" else {}))
                        flags = ["--command", command] if source == "flag" else []
                        self.call.reset_mock()
                        create.reset_mock()
                        code, out, err = self.cli("new", "--from", self.write_contract(contract), *flags)
                        self.assertNotEqual(code, 0, out + err)
                        self.assert_invalid_message(err)
                        self.call.assert_not_called()
                        create.assert_not_called()
                        self.assertFalse(self.ch.TASKS.exists())
        self.assertEqual(self.launches, [])
        self.ready.assert_not_called()
        self.deliver.assert_not_called()
        self.prepare_worktree.assert_not_called()

    def test_invalid_command_is_rejected_before_intent_drafting_or_git(self):
        with mock.patch.object(self.ch, "intent_draft", return_value=self.contract()) as draft:
            for source in ("json", "flag"):
                with self.subTest(source=source):
                    contract = self.contract(**({"command": "claude --model glm"} if source == "json" else {}))
                    flags = ["--command", "claude --model glm"] if source == "flag" else []
                    self.call.reset_mock()
                    code, out, err = self.cli("new", "Synthetic intent", "--from",
                                              self.write_contract(contract), *flags, "--dry-run")
                    self.assertNotEqual(code, 0, out + err)
                    self.assert_invalid_message(err)
                    self.call.assert_not_called()
                    draft.assert_not_called()

    def test_valid_command_does_not_allow_task_model_or_effort(self):
        for key in ("model", "effort"):
            with self.subTest(key=key):
                self.call.reset_mock()
                code, out, err = self.cli("new", "--from", self.write_contract(
                    self.contract(command="claude-mix", **{key: "override"})))
                self.assertNotEqual(code, 0, out + err)
                self.assertIn("--" + key, err)
                self.call.assert_not_called()

    def test_adopt_rejects_command_flag_without_launching_a_worker(self):
        code, out, err = self.cli("adopt", "0123456789abcdef", "--command", "claude-mix")
        self.assertNotEqual(code, 0, out + err)
        self.assertIn("--command", err)
        self.call.assert_not_called()
        self.ready.assert_not_called()
        self.deliver.assert_not_called()
        self.assertFalse(self.ch.TASKS.exists())


if __name__ == "__main__":
    unittest.main()
