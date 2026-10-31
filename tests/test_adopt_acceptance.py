"""Acceptance contract for supervising an existing conversation in place.

Run with: python3 -m unittest discover -s tests -p 'test_adopt_acceptance.py'
Some shared automation tests already pass; missing adoption and safety branches
must fail until the implementation is approved. External I/O is faked; spies
also catch attempts to create or rotate sessions without performing them.
"""
from datetime import timedelta
import os
from unittest import mock

import chief
import chief_tui as tui
from adoption_support import AdoptionFixture, FINAL, GOAL, NOTICE, READY, SID


class AdoptCommandTests(AdoptionFixture):
    def test_success_keeps_session_branch_head_and_worktree_and_sends_notice(self):
        refs = self.git("show-ref")
        worktrees = self.git("worktree", "list", "--porcelain")
        with mock.patch.object(chief, "start_task") as start:
            task = self.adopt("--id", "existing-plan")
        start.assert_not_called()
        self.assertEqual(task["id"], "existing-plan")
        self.assertIs(task["adopted"], True)
        self.assertEqual(task["session_id"], SID)
        self.assertEqual(task["repo"], str(self.repo))
        self.assertEqual(task["worktree"], str(self.repo))
        self.assertEqual(task["branch"], "agreed-plan")
        self.assertEqual(task["base"], self.base)
        self.assertEqual(task["tool"], "codex")
        self.assertEqual(task["name"], self.rec["title"])
        self.assertEqual(task["goal"], GOAL)
        self.assertEqual(task["checks"], chief.infer_checks(str(self.repo)))
        self.assertEqual(task["protected"], chief.infer_protected(str(self.repo)))
        self.assertIs(task["test_first"], False)
        self.assertEqual(task["phase"], "build")
        self.assertEqual(task["budget"], {"rounds": 15, "hours": 4})
        self.assertEqual(task["state"], "running")
        self.assertEqual(self.git("show-ref"), refs)
        self.assertEqual(self.git("worktree", "list", "--porcelain"), worktrees)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertTrue((self.repo / ".chief/progress.md").is_file())
        self.assertIn(".chief/", (self.repo / ".git/info/exclude").read_text())
        self.deliver.assert_called_once()
        args = self.deliver.call_args[0]
        self.assertEqual(args[1], SID)
        notice = args[2]
        for text in (NOTICE, task["name"], GOAL, task["checks"][0], "tests",
                     ".chief/progress.md", "Conclusion", "Evidence", "Blockers", "Next step", "Decision needed"):
            self.assertIn(text, notice)
        self.assertRegex(notice.lower(), r"commit")
        self.assertRegex(notice.lower(), r"continue.*plan|plan.*continue")
        self.assertRegex(notice.lower(), r"guess")
        self.assertIn(NOTICE, args[3])
        self.assertNotIn("the user is not watching", notice)
        self.assertFalse(any(op[0] == "add" for op in self.operations))

    def test_all_contract_flags_override_inference(self):
        task = self.adopt("--name", "Finish parser", "--goal", "Accept quoted fields",
                          "--check", "python3 check.py", "--check", "git diff --check",
                          "--protected", "config", "--protected", "tests/test_existing.py",
                          "--scope", "src", "--test-first", "--rounds", "7", "--hours", "1.5",
                          "--autonomy", "observe", "--id", "parser")
        for key, expected in dict(name="Finish parser", goal="Accept quoted fields", scope="src",
                                  checks=["python3 check.py", "git diff --check"],
                                  protected=["config", "tests/test_existing.py"],
                                  budget={"rounds": 7, "hours": 1.5}, autonomy="observe",
                                  test_first=True, phase="test").items():
            self.assertEqual(task[key], expected)

    def test_claude_title_is_preferred_and_session_prefix_is_accepted(self):
        self.rec["tool"] = "claude"
        self.write_records()
        self.conversation(title="The agreed parser plan")
        task = self.adopt(session=SID[:8])
        self.assertEqual(task["name"], "The agreed parser plan")
        self.assertEqual(task["tool"], "claude")

    def test_antigravity_is_supported_without_native_session_id(self):
        self.rec.update(tool="antigravity")
        self.rec.pop("agent_session_id")
        self.write_records()
        self.conversation()
        task = self.adopt()
        self.assertEqual(task["tool"], "antigravity")
        self.deliver.assert_called_once()

    def test_subdirectory_uses_git_top_level_but_keeps_project_path(self):
        self.rec["project_path"] = str(self.repo / "src")
        self.write_records()
        task = self.adopt()
        self.assertEqual(task["repo"], str(self.repo))
        self.assertEqual(task["worktree"], str(self.repo / "src"))
        self.assertTrue((self.repo / "src/.chief/progress.md").is_file())
        self.assertEqual(task["checks"], chief.infer_checks(str(self.repo)))

    def test_detached_head_is_recorded_as_null(self):
        self.git("checkout", "-q", "--detach", self.base)
        task = self.adopt()
        self.assertIsNone(task["branch"])
        self.assertEqual(task["base"], self.base)

    def test_tracked_annotation_does_not_count_as_board_ownership(self):
        self.cfg["tracked_ids"] = [SID]
        annotation = {"goal": "Observe this conversation", "parked": True}
        self.cfg["tasks"][SID] = annotation
        chief.save_cfg(self.cfg)
        self.adopt()
        self.assertEqual(chief.config()["tasks"][SID], annotation)

    def test_omitted_session_resolves_current_tmux_not_another_session(self):
        self.records["aaaaaaaaaaaaaaaa"] = dict(self.rec, id="aaaaaaaaaaaaaaaa", title="Other")
        self.write_records()
        with mock.patch.dict(os.environ, TMUX="/tmp/fake-tmux,12,0"):
            task = self.adopt(session=None)
        self.assertEqual(task["session_id"], SID)
        self.assertTrue(any(op[1] in ("display-message", "display") for op in self.tmux_operations),
                        "resolve the current tmux session, not whichever session lists first")

    def test_busy_or_menu_saves_needs_you_without_typing_and_kickoff_retries_notice(self):
        scenarios = [("running", READY), ("stopped", ""),
                     ("waiting", "Accept this file edit?\n> 1. Yes\n  2. No\n"),
                     ("idle", "Do you trust the contents of this project?\n> Yes, I trust this folder\n  No, exit\n")]
        for i, (status, screen) in enumerate(scenarios):
            with self.subTest(status=status):
                self.rec["status"], self.screen_text = status, screen
                self.write_records()
                task = self.adopt("--id", "not-ready-" + str(i))
                self.assertEqual(task["state"], "needs-you")
                self.assertRegex(task["note"], r"chief(?:\.py)? kickoff " + task["id"])
                self.assert_session_untouched()
                self.rec["status"], self.screen_text = "idle", READY
                self.write_records()
                code, out, err = self.cli("kickoff", task["id"])
                self.assertEqual(code, 0, out + err)
                self.deliver.assert_called_once()
                self.assertIn(NOTICE, self.deliver.call_args[0][2])
                self.assertEqual(chief.load_task(task["id"])["state"], "running")
                chief.save_task(dict(chief.load_task(task["id"]), state="done"))
                self.deliver.reset_mock()

    def test_dry_run_prints_contract_and_notice_without_any_changes(self):
        self.write("tests/test_existing.py", "# already edited by user\n")
        before = self.snapshot()
        with mock.patch.object(chief, "start_task") as start:
            code, out, err = self.cli("adopt", SID, "--dry-run", "--name", "Dry plan", "--id", "dry-plan")
        self.assertEqual(code, 0, out + err)
        for text in ("Dry plan", GOAL, NOTICE, "python3 -m unittest discover -s tests", "tests", str(self.repo)):
            self.assertIn(text, out)
        start.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assert_session_untouched()

    def test_dry_run_does_not_initialize_an_absent_chief_home(self):
        chief.CFG.unlink()
        self.home.rmdir()
        before = self.snapshot()
        code, out, err = self.cli("adopt", SID, "--dry-run")
        self.assertEqual(code, 0, out + err)
        self.assertIn(NOTICE, out)
        self.assertEqual(self.snapshot(), before)
        self.assert_session_untouched()


class AdoptRefusalTests(AdoptionFixture):
    def test_unknown_session(self):
        self.refused("adopt", "ffffffff", message=r"session|matches")

    def test_ambiguous_prefix(self):
        self.records["01234567aaaaaaaa"] = dict(self.rec, id="01234567aaaaaaaa")
        self.write_records()
        self.refused("adopt", SID[:8], message=r"ambiguous|matches|longer")

    def test_non_live_session(self):
        for state in ("archived", "trashed", "deleted"):
            with self.subTest(state=state):
                self.rec.update(state=state, archived=state == "archived")
                self.write_records()
                self.refused("adopt", SID, message=r"live|archiv|trash|delet")

    def test_non_terminal_session(self):
        self.rec["view"] = "browser"
        self.write_records()
        self.refused("adopt", SID, message=r"terminal")

    def test_unsupported_tool(self):
        self.rec["tool"] = "shell"
        self.write_records()
        self.refused("adopt", SID, message=r"tool|claude|codex|antigravity")

    def test_project_outside_git(self):
        other = self.root / "not-a-repo"
        other.mkdir()
        self.rec["project_path"] = str(other)
        self.write_records()
        self.refused("adopt", SID, message=r"git|repository")

    def test_repository_without_commits(self):
        empty = self.root / "unborn"
        empty.mkdir()
        self.git("-C", str(empty), "init", "-q")
        self.rec["project_path"] = str(empty)
        self.write_records()
        self.refused("adopt", SID, message=r"commit|head")

    def test_active_board_owner_in_every_active_state(self):
        for state in sorted(chief.ACTIVE):
            with self.subTest(state=state):
                self.seed_task(adopted=False, state=state)
                self.refused("adopt", SID, message=r"already|own|board|task")

    def test_existing_task_id_is_not_overwritten(self):
        self.seed_task(id="occupied", session_id="aaaaaaaaaaaaaaaa")
        self.refused("adopt", SID, "--id", "occupied", message=r"exist|taken|collision")

    def test_missing_session_outside_tmux(self):
        self.refused("adopt", message=r"session|tmux")

    def test_aoe_terminal_shell_is_not_the_worker(self):
        self.tmux_name = "aoe_term_plan_" + SID[:8]
        with mock.patch.dict(os.environ, TMUX="/tmp/fake-tmux,12,0"):
            self.refused("adopt", message=r"shell|aoe_term|terminal|worker")

    def test_non_aoe_tmux_session(self):
        self.tmux_name = "ordinary-terminal"
        with mock.patch.dict(os.environ, TMUX="/tmp/fake-tmux,12,0"):
            self.refused("adopt", message=r"aoe|session")


class AdoptProtectedTests(AdoptionFixture):
    def test_dirty_protected_files_are_exact_allowances_and_later_edits_turn_red(self):
        self.write("tests/test_existing.py", "# user approved edit\n")
        self.git("add", "tests/test_existing.py")
        self.write("config/policy.txt", "user approved policy\n")
        self.write("config/new.txt", "user approved addition\n")
        self.write("config/staged-new.txt", "staged addition\n")
        self.git("add", "config/staged-new.txt")
        task = self.adopt("--protected", "tests", "--protected", "config")
        allowed = {a["path"]: a for a in task["allowed"]}
        self.assertEqual(set(allowed), {"tests/test_existing.py", "config/policy.txt",
                                        "config/new.txt", "config/staged-new.txt"})
        for path in ("tests/test_existing.py", "config/policy.txt"):
            self.assertEqual(allowed[path]["kind"], "state")
            self.assertEqual(allowed[path]["hash"], chief.protected_content(self.repo / path)[0])
        for path in ("config/new.txt", "config/staged-new.txt"):
            self.assertEqual(allowed[path]["kind"], "addition")
        item = self.item()
        self.assertEqual(item["scope"]["protected_violations"], [])
        self.assertFalse(any(level == "red" and kind == "protected" for level, _, kind in item["signals"]))
        self.write("config/policy.txt", "agent changed the approved policy again\n")
        item = self.item()
        self.assertIn("config/policy.txt", item["scope"]["protected_violations"])
        self.assertTrue(any(level == "red" and kind == "protected" for level, _, kind in item["signals"]))
        self.assertEqual(item["decision"]["kind"], "protected-state")
        self.assertIn("config/policy.txt", item["decision"]["files"])
        self.deliver.reset_mock()
        chief.tick(self.cfg)
        self.deliver.assert_not_called()

    def test_preexisting_protected_deletion_is_approved_but_restoration_requires_permission(self):
        path = self.repo / "config/policy.txt"
        path.unlink()
        task = self.adopt("--protected", "config")
        allowed = {a["path"]: a for a in task["allowed"]}
        self.assertEqual(allowed["config/policy.txt"]["kind"], "state")
        self.assertEqual(allowed["config/policy.txt"]["hash"], "deleted")
        self.assertEqual(self.item()["scope"]["protected_violations"], [])
        path.write_text("different policy restored by agent\n", encoding="utf-8")
        self.assertIn("config/policy.txt", self.item()["scope"]["protected_violations"])

    def test_preexisting_unprotected_changes_remain_in_scope_scan_and_review(self):
        self.write("src/app.py", "value = 'preexisting user work'\n")
        self.write("src/new.py", "# preexisting new file\n")
        task = self.adopt("--scope", "config", "--check", "python3 -c 'pass'")
        item = self.item()
        self.assertIn("src/app.py", item["scope"]["out_of_scope"])
        self.assertIn("src/new.py", item["scope"]["out_of_scope"])
        with mock.patch.object(chief, "generate_ai", return_value="Verdict: pass\nSummary: reviewed\nIssues: none") as ai:
            chief.review_task(self.cfg, task, item)
        prompt = ai.call_args[0][0]
        self.assertIn("preexisting user work", prompt)
        self.assertIn("src/new.py", prompt)
        self.assertTrue((chief.TASKS / task["id"] / "review.md").is_file())


class AdoptAutomationTests(AdoptionFixture):
    def test_tick_runs_checks_after_each_completed_turn_and_continues_with_failures(self):
        task = self.seed_task()
        for turn in range(2):
            chief.tick(self.cfg)
            self.assertEqual(self.deliver.call_count, turn + 1)
            self.assertEqual(self.deliver.call_args[0][1], SID)
            self.assertIn("synthetic check failure", self.deliver.call_args[0][2])
            self.assertIn("python3 check.py", self.deliver.call_args[0][2])
            chief.tick(self.cfg)
            self.assertEqual(self.deliver.call_count, turn + 1, "don't continue twice for one turn")
            self.now += timedelta(minutes=1)
            self.conversation(prompt=chief.CONTINUE_MARK + " are not passing yet.", minutes=0.5)
        self.assertEqual(chief.load_task(task["id"])["auto"]["continues"], 2)

    def test_recent_human_prompt_pauses_then_resumes_for_all_worker_transcripts(self):
        for tool in ("claude", "codex", "antigravity"):
            with self.subTest(tool=tool):
                self.rec["tool"] = tool
                self.write_records()
                self.seed_task(tool=tool)
                self.conversation(minutes=2)
                self.deliver.reset_mock()
                chief.tick(self.cfg)
                self.deliver.assert_not_called()
                item = self.item()
                signal = " ".join(message for _, message, _ in item["signals"]).lower()
                self.assertRegex(signal, r"user.*active|active.*user")
                self.assertRegex(signal, r"paus")
                card = "\n".join(text for _, text in tui.entry(chief, item)["detail"])
                self.assertRegex(card.lower(), r"user.*active|active.*user")
                brief = chief.basic({"items": [item], "generated_at": self.now.isoformat()})
                self.assertRegex(brief.lower(), r"user.*active|active.*user")
                self.now += timedelta(minutes=9)
                chief.tick(self.cfg)
                self.deliver.assert_called_once()

    def test_presence_uses_prompt_start_not_recent_reply_and_honors_custom_window(self):
        self.seed_task()
        self.cfg["presence_minutes"] = 30
        self.conversation(minutes=20)
        chief.tick(self.cfg)
        self.deliver.assert_not_called()
        self.cfg["presence_minutes"] = 10
        chief.tick(self.cfg)
        self.deliver.assert_called_once()

    def test_presence_pauses_interrupted_turn_recovery(self):
        self.seed_task()
        self.conversation(minutes=1, finished=False, error=True)
        chief.tick(self.cfg)
        self.deliver.assert_not_called()
        self.now += timedelta(minutes=10)
        chief.tick(self.cfg)
        self.deliver.assert_called_once()
        self.assertIn("AoE Chief", self.deliver.call_args[0][2])

    def test_chief_markers_do_not_count_as_user_presence(self):
        messages = [NOTICE, "You are working on a delegated task managed by AoE Chief.",
                    chief.CONTINUE_MARK + " are not passing yet.",
                    "AoE Chief: your previous turn ended without finishing.",
                    chief.user_reply("Use JSON."), chief.draft_reply("Use JSON.")]
        for prompt in messages:
            with self.subTest(prompt=prompt):
                self.seed_task()
                self.conversation(prompt=prompt, minutes=1)
                self.deliver.reset_mock()
                chief.tick(self.cfg)
                self.deliver.assert_called_once()

    def test_nudge_bypasses_presence_and_its_message_does_not_pause_next_turn(self):
        task = self.seed_task()
        self.conversation(minutes=1)
        code, out, err = self.cli("nudge", task["id"], "Continue the agreed plan")
        self.assertEqual(code, 0, out + err)
        self.deliver.assert_called_once()
        prompt = self.deliver.call_args[0][2]
        self.assertIn("AoE Chief", prompt)
        self.conversation(prompt=prompt, minutes=0.5)
        self.deliver.reset_mock()
        chief.tick(self.cfg)
        self.deliver.assert_called_once()

    def test_presence_does_not_change_delegated_task_automation(self):
        self.seed_task(adopted=False)
        self.conversation(minutes=1)
        chief.tick(self.cfg)
        self.deliver.assert_called_once()

    def test_presence_defers_queued_protected_decision_notice_until_window_expires(self):
        task = self.seed_task()
        self.write("config/policy.txt", "requires permission\n")
        item = self.item()
        decision = chief.find_decision(item["decision"]["id"])
        self.rec["status"] = "running"
        self.write_records()
        chief.accept_decision(self.cfg, decision)
        self.assertEqual(chief.protected_notice_status(decision), "queued")
        self.rec["status"] = "idle"
        self.write_records()
        self.conversation(minutes=1)
        chief.tick(self.cfg)
        self.deliver.assert_not_called()
        self.assertEqual(chief.protected_notice_status(decision), "queued")
        self.now += timedelta(minutes=10)
        chief.tick(self.cfg)
        notices = [call for call in self.deliver.call_args_list if "approved" in call[0][2]]
        self.assertEqual(len(notices), 1)
        self.assertEqual(chief.protected_notice_status(decision), "delivered")
        self.assertTrue(chief.load_task(task["id"])["allowed"])

    def test_context_threshold_never_rotates_adopted_task(self):
        task = self.seed_task()
        self.screen_text = "Context 95% used\n" + READY
        with mock.patch.object(chief, "rotate_task") as rotate:
            chief.tick(self.cfg)
        rotate.assert_not_called()
        self.deliver.assert_called_once()
        self.assertEqual(self.deliver.call_args[0][1], SID)
        self.assertEqual(chief.load_task(task["id"])["session_id"], SID)

    def test_stuck_and_continue_cap_still_require_user(self):
        for setting, limit in (("stuck_after", 2), ("max_auto_continues", 1)):
            with self.subTest(setting=setting):
                self.seed_task()
                cfg = dict(self.cfg, **{setting: limit})
                self.deliver.reset_mock()
                chief.tick(cfg)
                self.now += timedelta(minutes=1)
                self.conversation(prompt=chief.CONTINUE_MARK, minutes=0.5)
                chief.tick(cfg)
                self.deliver.assert_called_once()
                task = chief.load_task("adopted-plan")
                self.assertEqual(task["state"], "needs-you")
                self.assertTrue(task.get("note"))

    def test_worker_question_enters_decision_queue_and_blocks_continuation(self):
        self.seed_task(autonomy="auto")
        question = "Change the public API? Options: A) keep B) replace. Recommendation: A"
        self.conversation(reply=FINAL.replace("Decision needed: none", "Decision needed: " + question))
        chief.tick(self.cfg)
        self.deliver.assert_not_called()
        self.assertEqual(self.item()["decision"]["question"], question)

    def test_opt_in_test_phase_blocks_build_automation_until_approval(self):
        self.seed_task(test_first=True, phase="test")
        chief.tick(self.cfg)
        self.deliver.assert_not_called()
        self.assertEqual(chief.load_task("adopted-plan")["phase"], "test")

    def test_passing_checks_trigger_cross_review_and_persist_card(self):
        task = self.seed_task(checks=["python3 -c 'pass'"])
        self.cfg["review"] = True
        response = "Verdict: pass\nSummary: Agreed plan complete\nRisks: none\nLook at: src/app.py\nIssues: none"
        with mock.patch.object(chief, "generate_ai", return_value=response) as ai:
            chief.tick(self.cfg)
            chief.tick(self.cfg)
        ai.assert_called_once()
        self.assertNotEqual(ai.call_args[0][1], task["tool"])
        self.assertEqual(chief.load_task(task["id"])["review"]["verdict"], "pass")
        self.assertIn("Agreed plan complete", (chief.TASKS / task["id"] / "review.md").read_text())
        self.deliver.assert_not_called()


class AdoptReleaseTests(AdoptionFixture):
    def test_close_and_abandon_release_without_session_side_effects(self):
        for flags, state in (([], "done"), (["--abandon"], "abandoned")):
            with self.subTest(state=state):
                task = self.seed_task()
                before_repo = {str(p.relative_to(self.repo)): p.read_bytes()
                               for p in self.repo.rglob("*") if p.is_file()}
                code, out, err = self.cli("close", task["id"], *flags)
                self.assertEqual(code, 0, out + err)
                closed = chief.load_task(task["id"])
                self.assertEqual(closed["state"], state)
                self.assertFalse(closed.get("session_archived"))
                self.assertFalse(closed.get("session_removed"))
                self.assert_session_untouched()
                self.assertEqual({str(p.relative_to(self.repo)): p.read_bytes()
                                  for p in self.repo.rglob("*") if p.is_file()}, before_repo)

    def test_close_remove_session_is_refused_even_with_force(self):
        task = self.seed_task()
        self.refused("close", task["id"], "--remove-session", "--force", message=r"adopt|release")

    def test_explicit_rotation_is_refused(self):
        task = self.seed_task()
        code, out, err = self.cli("rotate", task["id"])
        self.assertNotEqual(code, 0, out + err)
        self.assertRegex((out + err).lower(), r"adopted|in.place|cannot rotate")
        self.assertEqual(chief.load_task(task["id"])["session_id"], SID)
        self.assert_session_untouched()

    def test_clean_never_lists_or_removes_adopted_tasks_or_their_branches(self):
        for state in ("done", "abandoned"):
            with self.subTest(state=state):
                task = self.seed_task(state=state)
                before = self.snapshot()
                for flags in ([], ["--dry-run"], ["--branches"]):
                    with mock.patch("builtins.input", return_value="y") as ask:
                        code, out, err = self.cli("clean", *flags)
                    self.assertEqual(code, 0, out + err)
                    self.assertNotIn(task["id"], out)
                    ask.assert_not_called()
                    self.assertEqual(self.snapshot(), before)
                    self.assert_session_untouched()

    def test_release_restores_preexisting_plain_tracking_and_annotation(self):
        self.cfg["tracked_ids"] = [SID]
        annotation = {"goal": "Original observation", "checks": [], "parked": True}
        self.cfg["tasks"][SID] = annotation
        chief.save_cfg(self.cfg)
        task = self.adopt()
        self.deliver.reset_mock()
        code, out, err = self.cli("close", task["id"])
        self.assertEqual(code, 0, out + err)
        cfg = chief.config()
        self.assertIn(SID, cfg["tracked_ids"])
        self.assertEqual(cfg["tasks"][SID], annotation)
        item = next(i for i in chief.collect(cfg, persist=False)["items"] if i["id"] == SID)
        self.assertEqual(item["task"], annotation)
        self.assertEqual(tui.entry(chief, item)["group"], "thinking")
        chief.tick(cfg)
        self.assert_session_untouched()

    def test_released_session_can_be_adopted_again_without_rewriting_old_record(self):
        old = self.seed_task(state="done")
        task = self.adopt("--id", "new-adoption")
        self.assertNotEqual(old["id"], task["id"])
        self.assertEqual(chief.load_task(old["id"]), old)
