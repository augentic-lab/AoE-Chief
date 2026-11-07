"""Accept Chief-managed Codex updates through real task/decision/CLI/tick flows.

Only external boundaries are simulated. The existing wait_ready, collect,
decision persistence, console key handling and kickoff code run normally. Every
process/terminal action is allowlisted: no npm, AoE, tmux or network is invoked.
The pending step's representation is deliberately unspecified; its behavior must
survive a storage reload and preserve fresh versus rotation kickoff semantics.
"""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import json
import os
import subprocess
from unittest import mock

import chief
import chief_tui
from test_intent_task_flow import ChiefFixture
from test_codex_update_menu_acceptance import REAL_SCREEN, AFTER_SKIP_SCREEN


OLD = "0.162.1"
TARGET = "0.165.0"
SID = "0123456789abcdef"
OLD_SID = "fedcba9876543210"
SECOND_SID = "1123456789abcdef"
READY = "› Ask Codex to do anything\n"


class CodexUpdateResumeAcceptance(ChiefFixture):
    def setUp(self):
        super().setUp()
        self.cfg.update(aoe_colors=False, codex_update_command=[
            "update-codex-fixture", "--target={version}", "--prefix", "~/.npm-global",
            "literal argument; $(must-not-run)"])
        chief.save_cfg(self.cfg)
        self.screens = {}
        self.statuses = {}
        self.versions = {"codex": OLD, "codex-worker": OLD}
        self.after_update = TARGET
        self.update_code = 0
        self.update_exception = None
        self.version_code = 0
        self.after_start = READY
        self.delivery_ok = True
        self.launch_sid = SID
        self.timeline = []
        self.log = {"turn": "done", "last_ts": "2026-11-07T00:00:00+00:00"}
        self.clock = 0.0

    def task(self, tid="update-worker", sid=SID, **changes):
        t = dict(id=tid, name="Update worker " + tid, goal="Finish the delegated work",
                 repo=str(self.repo), worktree=str(self.repo), branch="chief/" + tid,
                 tool="codex", state="running", session_id=sid, base="a" * 40,
                 autonomy="observe", phase="build", test_first=False, checks=[], protected=[])
        t.update(changes)
        return t

    def resolved(self, name):
        return str(self.root / "worker bin" / name)

    def expected_update(self, version=TARGET):
        command = self.cfg.get("codex_update_command", [
            "npm", "install", "-g", "@openai/codex@{version}", "--prefix", "~/.npm-global"])
        return [os.path.expanduser(arg.replace("{version}", version)) for arg in command]

    def records(self, cfg):
        return {sid: dict(id=sid, tool="codex", status=self.statuses.get(sid, "waiting"),
                          project_path=str(self.repo)) for sid in self.screens}

    def process(self, argv, **kwargs):
        self.assertIsInstance(argv, (list, tuple), "commands must be argv, never shell strings")
        argv = list(argv)
        self.assertFalse(kwargs.get("shell", False), "never use a shell for updates or notifications")
        self.assertIsInstance(kwargs.get("timeout"), (int, float), "external commands need a timeout")
        self.assertGreater(kwargs["timeout"], 0)
        self.timeline.append(("process", argv))
        if argv[0] == "aoe-fixture" and "add" in argv:
            return subprocess.CompletedProcess(argv, 0, "ID: {}\nPath: {}\n".format(
                self.launch_sid, self.repo), "")
        if argv == self.expected_update() or argv == self.expected_update("latest"):
            self.timeline.append(("update", argv))
            if self.update_exception:
                raise self.update_exception
            if self.update_code == 0:
                for name in self.versions:
                    self.versions[name] = self.after_update
            return subprocess.CompletedProcess(argv, self.update_code,
                                               "update-output-tail\n", "update-error-tail\n")
        if len(argv) == 2 and argv[1] == "--version":
            name = Path(argv[0]).name
            self.assertIn(name, self.versions, "verify the worker's actual launcher")
            self.assertIn(argv[0], (name, self.resolved(name)))
            value = self.versions[name]
            self.timeline.append(("version", name, value))
            return subprocess.CompletedProcess(argv, self.version_code,
                                               "codex-cli {}\n".format(value), "version-check-failed")
        notify = self.cfg.get("notify_command")
        if notify and argv[0] == notify[0]:
            self.assertEqual(len(argv), 2, "notification receives only the substituted message")
            self.timeline.append(("notify", argv))
            return subprocess.CompletedProcess(argv, 0, "", "")
        self.fail("unexpected process (including updater fallback or terminal keys): " + repr(argv))

    def aoe(self, cfg, *args):
        if args[:3] == ("session", "show", "--json"):
            return json.dumps({"status": self.statuses.get(args[3], "waiting")})
        if len(args) == 3 and args[:2] in (("session", "stop"), ("session", "start")):
            action, sid = args[1:]
            self.timeline.append((action, sid))
            if action == "start":
                self.screens[sid] = self.after_start
                self.statuses[sid] = "waiting"
            return ""
        self.fail("unexpected AoE action; restart and menu input are forbidden: " + repr(args))

    def deliver(self, cfg, sid, text, marker):
        self.assertFalse(chief.UPDATE_RE.search(self.screens.get(sid, "")),
                         "never send a decision, Enter, a digit or kickoff into the update menu")
        self.timeline.append(("deliver", sid, text))
        return self.delivery_ok

    @contextmanager
    def runtime(self):
        def sleep(seconds):
            self.clock += seconds

        real_wait = chief.wait_ready

        def wait(*args, **kwargs):
            result = real_wait(*args, **kwargs)
            self.timeline.append(("ready", args[1], result))
            return result

        with ExitStack() as stack:
            patches = [
                mock.patch.object(chief, "aoe", side_effect=self.aoe),
                mock.patch.object(chief, "aoe_bin", return_value="aoe-fixture"),
                mock.patch.object(chief, "aoe_records", side_effect=self.records),
                mock.patch.object(chief, "screen", side_effect=lambda cfg, sid: self.screens.get(sid, "")),
                mock.patch.object(chief, "listings", side_effect=lambda cfg: [
                    {"id": sid, "state": "live", "title": sid} for sid in self.screens]),
                mock.patch.object(chief, "transcript", side_effect=lambda rec: self.log if rec else None),
                mock.patch.object(chief, "git_head", return_value="a" * 40),
                mock.patch.object(chief, "git_info", return_value=None),
                mock.patch.object(chief, "artifact_info", return_value=None),
                mock.patch.object(chief, "scope_info", return_value=None),
                mock.patch.object(chief, "pick_checks", return_value=None),
                mock.patch.object(chief, "prepare_worktree"),
                mock.patch.object(chief, "add_command", return_value=["aoe-fixture", "add", "--launch"]),
                mock.patch.object(chief, "deliver", side_effect=self.deliver),
                mock.patch.object(chief, "wait_ready", side_effect=wait),
                mock.patch.object(chief.shutil, "which", side_effect=lambda name: self.resolved(name)),
                mock.patch.object(chief.time, "time", side_effect=lambda: self.clock),
                mock.patch.object(chief.time, "sleep", side_effect=sleep),
                mock.patch.object(chief.subprocess, "run", side_effect=self.process),
                mock.patch.object(chief.subprocess, "Popen", side_effect=AssertionError("unexpected process")),
                mock.patch.object(chief.os, "system", side_effect=AssertionError("shell forbidden")),
                mock.patch.object(chief, "tmux_target", side_effect=AssertionError("menu keys forbidden")),
                mock.patch.object(chief, "answer_trust_menu", side_effect=AssertionError("menu keys forbidden")),
                mock.patch.object(chief.threading.Thread, "start", side_effect=AssertionError("unexpected thread")),
            ]
            for patch in patches:
                stack.enter_context(patch)
            yield

    def block(self, path="kickoff", tid="update-worker", sid=SID, menu=REAL_SCREEN, **changes):
        t = self.task(tid, OLD_SID if path == "rotation" else sid, **changes)
        self.screens[sid] = menu
        if path == "rotation":
            self.screens[OLD_SID] = READY
        self.launch_sid = sid
        chief.save_task(t)
        if path == "start":
            chief.start_task(self.cfg, t)
        elif path == "rotation":
            chief.rotate_task(self.cfg, t, {"log": {"turns_total": 3}}, "context rotation")
        else:
            code, out, err = self.cli("kickoff", tid)
            self.assertIn(code, (0, 1), out + err)
        return chief.load_task(tid)

    def decision(self, tid="update-worker"):
        decisions = [d for d in chief.load_decisions(tid) if d.get("kind") == "codex-update"
                     and d["state"] == "pending"]
        self.assertEqual(len(decisions), 1, "queue exactly one pending codex-update decision per task")
        return decisions[0]

    def assert_waiting(self, tid="update-worker", versions=(OLD, TARGET)):
        t = chief.load_task(tid)
        self.assertEqual(t["state"], "needs-you")
        self.assertTrue(t.get("note"))
        pending = t.get("pending_resume")
        self.assertIsInstance(pending, dict, "persist the interrupted step as pending_resume")
        self.assertEqual(pending.get("kind"), "codex-update")
        self.assertTrue(pending.get("step"))
        self.assertEqual((pending.get("from"), pending.get("to")), versions)
        self.assertIsNotNone(chief.parse_ts(pending.get("since")))
        return t

    def assert_resumed(self, tid="update-worker", sid=SID, rotation=False):
        t = chief.load_task(tid)
        self.assertEqual(t["state"], "running")
        self.assertFalse(t.get("pending_resume"))
        self.assertFalse(t.get("note"))
        deliveries = [e for e in self.timeline if e[:2] == ("deliver", sid)]
        self.assertEqual(len(deliveries), 1, "resume exactly once after verified readiness")
        self.assertEqual(deliveries[0][2], chief.kickoff_prompt(t, resume=rotation))
        self.assertFalse(any(d["state"] == "pending" and d.get("kind") == "codex-update"
                             for d in chief.load_decisions(tid)))
        events = json.dumps(chief.events_since(t, None)).lower()
        self.assertRegex(events, r"resum|continu|kickoff", "log continuation to the task events")

    def accept(self, decision=None):
        d = decision or self.decision()
        code, out, err = self.cli("decide", d["id"], "--accept")
        self.assertEqual(code, 0, out + err)

    def actions(self, name):
        return [e for e in self.timeline if e[0] == name]

    def test_all_three_entry_points_persist_versions_step_and_one_actionable_decision(self):
        with self.runtime():
            for path in ("start", "rotation", "kickoff"):
                with self.subTest(path=path):
                    tid = "blocked-" + path
                    self.block(path, tid)
                    self.assert_waiting(tid)
                    d = self.decision(tid)
                    self.assertIn(OLD, d["question"])
                    self.assertIn(TARGET, d["question"])
                    text = (d.get("choice") or "") + " " + (d.get("draft") or "")
                    self.assertIn("update-codex-fixture", text)
                    self.assertIn("--target=" + TARGET, text)
                    self.assertRegex(text.lower(), r"run|execut|updat")
            self.assertEqual(self.actions("update"), [])
            self.assertEqual(self.actions("deliver"), [])

    def test_reobserving_the_same_menu_and_ticks_do_not_duplicate_or_supersede_the_decision(self):
        with self.runtime():
            self.block()
            first = self.decision()
            pending = self.assert_waiting()["pending_resume"]
            self.cli("kickoff", "update-worker")
            self.log = {"turn": "done", "last_ts": "2026-11-07T01:00:00+00:00"}
            chief.tick(self.cfg)
            chief.tick(self.cfg)
            self.assertEqual(self.decision()["id"], first["id"])
            self.assertEqual(self.assert_waiting()["pending_resume"]["since"], pending["since"])
            self.assertEqual(self.actions("update"), [])
            self.assertEqual(self.actions("deliver"), [])

    def test_cli_and_console_show_the_card_and_a_runs_the_same_acceptance_flow(self):
        with self.runtime():
            self.block()
            d = self.decision()
            code, out, err = self.cli("decisions")
            self.assertEqual(code, 0, err)
            for text in (d["id"], OLD, TARGET, "update-codex-fixture"):
                self.assertIn(text, out)
            board = chief.collect(self.cfg, checks=False)
            entries = chief_tui.entries(chief, board)
            entry = next(e for e in entries if e["task"] == "update-worker")
            self.assertEqual(entry["decision"]["id"], d["id"])
            self.assertTrue(any(k.startswith("a ") for k in chief_tui.keys_for(chief, entry)))
            app = chief_tui.Inbox(self.cfg, chief, 15)
            app.st.update(entries=[entry], sel=0)
            with mock.patch.object(app, "job", side_effect=lambda label, fn, **kw: fn()):
                app.key("a")
            self.assertEqual(len(self.actions("update")), 1)
            self.assert_resumed()

    def test_accept_checks_version_then_stop_start_and_resumes_the_recorded_step(self):
        with self.runtime():
            for path in ("start", "rotation", "kickoff"):
                with self.subTest(path=path):
                    tid = "accept-" + path
                    self.versions["codex"] = OLD
                    self.block(path, tid)
                    d = self.decision(tid)
                    self.timeline.clear()
                    with mock.patch.object(chief, "send_kickoff", wraps=chief.send_kickoff) as kickoff:
                        self.accept(d)
                    self.assertEqual(self.actions("update"), [("update", self.expected_update())])
                    verified = next(i for i, e in enumerate(self.timeline)
                                    if e == ("version", "codex", TARGET))
                    stop = self.timeline.index(("stop", SID))
                    start = self.timeline.index(("start", SID))
                    ready = self.timeline.index(("ready", SID, "ready"))
                    sent = next(i for i, e in enumerate(self.timeline) if e[0] == "deliver")
                    self.assertLess(verified, stop)
                    self.assertLess(stop, start)
                    self.assertLess(start, ready)
                    self.assertLess(ready, sent)
                    self.assertEqual(kickoff.call_count, 0 if path == "rotation" else 1)
                    self.assert_resumed(tid, rotation=path == "rotation")
                    events = json.dumps(chief.events_since(chief.load_task(tid), None))
                    for text in ("update-codex-fixture", "--target=" + TARGET, "update-output-tail"):
                        self.assertIn(text, events)
                    self.assertRegex(events.lower(), r"(?:exit|code|returncode)[^\n]{0,30}0")

    def test_default_update_argv_uses_the_custom_npm_prefix(self):
        self.cfg.pop("codex_update_command")
        chief.save_cfg(self.cfg)
        with self.runtime():
            self.block()
            self.accept()
            self.assertEqual(self.actions("update"), [("update", [
                "npm", "install", "-g", "@openai/codex@" + TARGET,
                "--prefix", os.path.expanduser("~/.npm-global")])])
            self.assert_resumed()

    def test_structured_version_check_uses_task_launcher_before_default_or_config_launcher(self):
        self.cfg["commands"] = {"codex": "codex-configured"}
        self.versions["codex-configured"] = "99.0.0"
        chief.save_cfg(self.cfg)
        with self.runtime():
            self.block(command="codex-worker")
            self.timeline.clear()
            self.accept()
            self.assertIn(("version", "codex-worker", TARGET), self.timeline)
            self.assertFalse(any(e[0] == "version" and e[1] != "codex-worker" for e in self.timeline))
            self.assert_resumed()

    def test_failed_or_timed_out_update_leaves_the_decision_actionable_without_fallback(self):
        with self.runtime():
            for failure in ("exit", "timeout", "missing"):
                with self.subTest(failure=failure):
                    tid = "failure-" + failure
                    self.block(tid=tid)
                    d = self.decision(tid)
                    self.update_code = 23 if failure == "exit" else 0
                    self.update_exception = ({"timeout": subprocess.TimeoutExpired(
                        self.expected_update(), 30, output="timed-out-tail"),
                        "missing": FileNotFoundError("updater missing")}.get(failure))
                    self.timeline.clear()
                    code, out, err = self.cli("decide", d["id"], "--accept")
                    self.assert_waiting(tid)
                    saved = chief.find_decision(d["id"])
                    self.assertIn(saved["state"], ("pending", "failed"))
                    events = json.dumps(chief.events_since(chief.load_task(tid), None))
                    text = out + err + events
                    self.assertRegex(text.lower(), r"fail|tim(?:e|ed).?out|missing")
                    self.assertIn("update-codex-fixture", events)
                    if failure == "exit":
                        self.assertIn("23", events)
                        self.assertIn("update-error-tail", events)
                    self.assertEqual(len(self.actions("update")), 1)
                    self.assertEqual(self.actions("stop") + self.actions("start") + self.actions("deliver"), [])
                    self.update_code, self.update_exception = 0, None

    def test_successful_installer_cannot_resume_with_old_malformed_or_failed_version_check(self):
        with self.runtime():
            for label, version, code in (("old", OLD, 0), ("unparseable", "unknown", 0),
                                         ("failed", TARGET, 1), ("prerelease", TARGET + "-rc.1", 0)):
                with self.subTest(case=label):
                    tid = "verify-" + label
                    self.versions["codex"] = OLD
                    self.block(tid=tid)
                    d = self.decision(tid)
                    self.after_update, self.version_code = version, code
                    self.timeline.clear()
                    self.cli("decide", d["id"], "--accept")
                    self.assert_waiting(tid)
                    self.assertIn(chief.find_decision(d["id"])["state"], ("pending", "failed"))
                    self.assertEqual(len(self.actions("update")), 1)
                    self.assertIn(("version", "codex", version), self.timeline)
                    self.assertEqual(self.actions("stop") + self.actions("start") + self.actions("deliver"), [])
                    self.version_code = 0

    def test_semver_comparison_accepts_a_newer_version_numerically(self):
        self.after_update = "0.1000.0"
        with self.runtime():
            self.block()
            self.accept()
            self.assert_resumed()

    def test_same_target_shares_one_update_and_resumes_both_fresh_and_rotation_steps(self):
        with self.runtime():
            self.block("start", "first", SID)
            self.block("rotation", "second", SECOND_SID)
            self.decision("first")
            chosen = self.decision("second")
            self.timeline.clear()
            self.accept(chosen)
            self.assertEqual(len(self.actions("update")), 1)
            self.assertEqual(sorted(self.actions("stop")), [("stop", SID), ("stop", SECOND_SID)])
            self.assertEqual(sorted(self.actions("start")), [("start", SID), ("start", SECOND_SID)])
            self.assert_resumed("first", SID)
            self.assert_resumed("second", SECOND_SID, rotation=True)
            chief.tick(self.cfg)
            self.assertEqual(len(self.actions("update")), 1)
            self.assertEqual(len(self.actions("deliver")), 2)

    def test_a_different_target_does_not_resume_after_the_shared_update(self):
        with self.runtime():
            self.block(tid="first")
            self.block(tid="future", sid=SECOND_SID, menu=REAL_SCREEN.replace(TARGET, "0.170.0"))
            self.timeline.clear()
            self.accept(self.decision("first"))
            self.assert_resumed("first")
            self.assert_waiting("future", versions=(OLD, "0.170.0"))
            self.decision("future")
            self.assertNotIn(("start", SECOND_SID), self.timeline)

    def test_tick_detects_a_hand_update_and_resolves_done_by_user_without_installer(self):
        with self.runtime():
            for index, status in enumerate(("waiting", "stopped")):
                with self.subTest(status=status):
                    tid = "hand-update-" + status
                    sid = "{:016x}".format(256 + index)
                    self.versions["codex"] = OLD
                    self.block("rotation", tid, sid)
                    d = self.decision(tid)
                    self.versions["codex"] = TARGET
                    self.statuses[sid] = status
                    self.timeline.clear()
                    chief.tick(self.cfg)
                    self.assertEqual(self.actions("update"), [])
                    self.assertEqual(self.actions("stop"), [("stop", sid)])
                    self.assertEqual(self.actions("start"), [("start", sid)])
                    self.assert_resumed(tid, sid, rotation=True)
                    self.assertEqual(chief.find_decision(d["id"]).get("resolution"), "done-by-user")
                    chief.tick(self.cfg)
                    self.assertEqual(len(self.actions("deliver")), 1)

    def test_tick_with_unknown_target_requires_a_changed_version_before_restarting(self):
        with self.runtime():
            with mock.patch.object(chief, "wait_ready", return_value="update"):
                self.block(menu="")
            d = self.decision()
            self.assert_waiting(versions=(None, None))
            self.screens[SID] = REAL_SCREEN
            chief.tick(self.cfg)
            self.assertEqual(self.actions("update") + self.actions("start") + self.actions("deliver"), [])
            self.versions["codex"] = TARGET
            self.timeline.clear()
            chief.tick(self.cfg)
            self.assertEqual(self.actions("update"), [])
            self.assertEqual(self.actions("start"), [("start", SID)])
            self.assert_resumed()
            self.assertEqual(chief.find_decision(d["id"]).get("resolution"), "done-by-user")

    def test_menu_dismissed_by_user_continues_directly_without_restart_or_install(self):
        with self.runtime():
            for index, path in enumerate(("start", "rotation", "kickoff")):
                with self.subTest(path=path):
                    tid = "dismiss-" + path
                    sid = "{:016x}".format(512 + index)
                    self.block(path, tid, sid)
                    d = self.decision(tid)
                    self.screens[sid] = AFTER_SKIP_SCREEN
                    self.timeline.clear()
                    chief.tick(self.cfg)
                    self.assertEqual(self.actions("update") + self.actions("stop") + self.actions("start"), [])
                    self.assert_resumed(tid, sid, rotation=path == "rotation")
                    self.assertNotEqual(chief.find_decision(d["id"])["state"], "pending")

    def test_menu_absence_alone_does_not_allow_input_to_an_unready_session(self):
        with self.runtime():
            self.block()
            self.screens[SID] = "Codex is still loading...\n"
            self.timeline.clear()
            chief.tick(self.cfg)
            self.assert_waiting()
            self.assertEqual(self.actions("deliver") + self.actions("update") + self.actions("start"), [])

    def test_unknown_menu_versions_use_latest_and_require_a_changed_structured_version(self):
        with self.runtime():
            for changed in (False, True):
                with self.subTest(changed=changed):
                    tid = "unknown-" + str(changed).lower()
                    self.versions["codex"] = OLD
                    # The detector saw the menu, but re-observation lost its versions.
                    with mock.patch.object(chief, "wait_ready", return_value="update"):
                        self.block(tid=tid, menu="")
                    self.assert_waiting(tid, versions=(None, None))
                    self.after_update = TARGET if changed else OLD
                    self.timeline.clear()
                    self.cli("decide", self.decision(tid)["id"], "--accept")
                    self.assertEqual(self.actions("update"), [("update", self.expected_update("latest"))])
                    if changed:
                        self.assert_resumed(tid)
                    else:
                        self.assert_waiting(tid, versions=(None, None))
                        self.assertEqual(self.actions("start") + self.actions("deliver"), [])
                    # Keep the other subcase outside the next shared update group.
                    t = chief.load_task(tid)
                    t["state"] = "done"
                    t.pop("pending_resume", None)
                    chief.save_task(t)

    def test_restarted_worker_still_blocked_stays_needs_you_without_looping(self):
        with self.runtime():
            for label, result in (("update", REAL_SCREEN), ("timeout", "Loading..."),
                                  ("trust", "Trust this folder?\n")):
                with self.subTest(readiness=label):
                    tid = "restart-" + label
                    self.versions["codex"] = OLD
                    self.block(tid=tid)
                    d = self.decision(tid)
                    self.after_start = result
                    self.timeline.clear()
                    self.cli("decide", d["id"], "--accept")
                    self.assert_waiting(tid)
                    self.assertIn(label, chief.load_task(tid)["note"].lower())
                    self.assertEqual(len(self.actions("update")), 1)
                    self.assertEqual(self.actions("stop"), [("stop", SID)])
                    self.assertEqual(self.actions("start"), [("start", SID)])
                    self.assertEqual(self.actions("deliver"), [])
                    t = chief.load_task(tid)
                    t["state"] = "done"
                    t.pop("pending_resume", None)
                    chief.save_task(t)

    def test_unconfirmed_kickoff_delivery_does_not_claim_running(self):
        self.delivery_ok = False
        with self.runtime():
            self.block()
            self.cli("decide", self.decision()["id"], "--accept")
            t = chief.load_task("update-worker")
            self.assertEqual(t["state"], "needs-you")
            self.assertRegex(t.get("note", "").lower(), r"unconfirmed|may not|not.*confirm")
            self.assertEqual(len(self.actions("deliver")), 1)

    def test_notify_command_receives_only_the_message_once_per_new_card(self):
        self.cfg["notify_command"] = ["notify-fixture", "{message}"]
        chief.save_cfg(self.cfg)
        with self.runtime():
            self.block()
            first = self.decision()
            self.cli("kickoff", "update-worker")
            chief.tick(self.cfg)
            chief.tick(self.cfg)
            self.assertEqual(self.decision()["id"], first["id"])
            notices = self.actions("notify")
            self.assertEqual(len(notices), 1)
            argv = notices[0][1]
            self.assertEqual(argv[0], "notify-fixture")
            self.assertEqual(len(argv), 2)
            for text in (OLD, TARGET):
                self.assertIn(text, argv[1])
            self.assertNotIn("{message}", argv[1])
            self.assertEqual(self.actions("update"), [])

    def test_dry_tick_does_not_resume_or_resolve_a_hand_update(self):
        with self.runtime():
            self.block()
            d = self.decision()
            self.versions["codex"] = TARGET
            self.timeline.clear()
            chief.tick(self.cfg, dry=True)
            self.assert_waiting()
            self.assertEqual(chief.find_decision(d["id"])["state"], "pending")
            self.assertEqual(self.actions("update") + self.actions("stop") + self.actions("start") +
                             self.actions("deliver"), [])
