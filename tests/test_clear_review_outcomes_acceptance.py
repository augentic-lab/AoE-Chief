"""Cross-review acceptance contract, with no real AI, Git, AoE, or tmux calls.

Exercise real collection, triage, CLI/view formatting, review parsing, tick,
nudge wording, and on-disk task/event storage. Only environment I/O is faked.
Outcome labels are deliberately user-facing: waiting for cross review, ready
to accept, ready with risks, and needs work. Internal field/helper names for
review return tracking are left to the implementation.
"""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import chief
import chief_tui as tui


SID = "0123456789abcdef"
ISSUE = "1. src/cache.py:24: invalidate the cached result after writes."
RISK = "src/cache.py:31: eviction can briefly increase read latency."
READY = r"(?i)ready (?:for you )?to accept"
WAITING = r"(?i)waiting (?:for (?:the )?)?cross[ -]review"


class ReviewFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        home = self.root / "state"
        paths = {"CFG": "config.json", "CHECKS": "checks.json", "LAST": "latest.json",
                 "TICK": "tick.json", "TASKS": "tasks", "BRIEF": "latest.md",
                 "ARCHIVE": "reports", "PREFS": "preferences.md"}
        self.stack.enter_context(mock.patch.multiple(
            chief, ROOT=home, LANG="en", **{k: home / v for k, v in paths.items()}))
        self.cfg = chief.config()
        self.cfg.update(aoe_colors=False, decision_ai=False)
        chief.save_cfg(self.cfg)
        self.head = "a" * 40
        self.status = "idle"
        self.log = dict(turn="done", last_ts=chief.now_utc().isoformat(), footer={},
                        last_prompt="AoE Chief: delegated task", last_reply="Finished.")
        self.task = dict(id="cache", name="Cache invalidation", goal="Invalidate after writes",
                         repo=str(self.repo), worktree=str(self.repo), base="0" * 40,
                         session_id=SID, state="running", tool="codex", phase="build",
                         autonomy="suggest", checks=["check-cache", "check-regressions"],
                         scope="src", protected=["tests"])
        chief.save_task(self.task)
        self.checks = dict(at=chief.now_utc().isoformat(), passed=2, total=2,
                          cmds=self.task["checks"], results=[
                              dict(cmd=cmd, ok=True, code=0, tail="OK")
                              for cmd in self.task["checks"]])
        self.answer = self.review_text("pass")
        self.sent = []
        self.patch("listings", side_effect=lambda cfg: [dict(id=SID, state="live")])
        self.patch("aoe_records", side_effect=lambda cfg: {SID: self.record()})
        self.patch("aoe", side_effect=self.aoe)
        self.patch("transcript", side_effect=lambda rec: copy.deepcopy(self.log))
        self.patch("recent_turns", return_value=[])
        self.patch("screen", return_value=None)
        self.patch("git_info", side_effect=lambda path: dict(
            head=self.head, dirty=0, branch="worker/cache", last_commit="Invalidate cache",
            last_commit_at=self.log["last_ts"]))
        self.patch("scope_info", return_value=None)
        self.patch("run_checks", side_effect=lambda *a, **kw: copy.deepcopy(self.checks))
        self.patch("wait_ready", return_value="ready")
        self.delivery = self.patch("deliver", side_effect=self.deliver)
        self.ai = self.patch("generate_ai", side_effect=lambda *a, **kw: self.answer)
        self.patch("call", side_effect=self.git_read)
        # Fail closed if any path tries to launch a real process or sleep.
        for name in ("run", "Popen", "call", "check_call", "check_output"):
            self.stack.enter_context(mock.patch.object(
                chief.subprocess, name, side_effect=AssertionError("unexpected subprocess")))
        self.stack.enter_context(mock.patch.object(
            chief.time, "sleep", side_effect=AssertionError("unexpected sleep")))

    def patch(self, name, **kwargs):
        return self.stack.enter_context(mock.patch.object(chief, name, **kwargs))

    def record(self):
        return dict(id=SID, project_path=str(self.repo), status=self.status, tool="codex")

    def aoe(self, cfg, *args, **kwargs):
        self.assertEqual(args, ("session", "show", "--json", SID))
        return json.dumps(self.record())

    def git_read(self, args, **kwargs):
        self.assertEqual(args[:3], ["git", "-C", str(self.repo)])
        self.assertIn(args[3], ("diff", "log", "ls-files"))
        return ""  # Synthetic, clean committed worktree; no shell or Git execution.

    def deliver(self, cfg, sid, text, *args, **kwargs):
        self.assertEqual(sid, SID)
        self.sent.append(text)
        return True

    def review_text(self, verdict, issues="", risks=""):
        return ("Verdict: {}\nSummary: Cache changes reviewed.\nRisks: {}\n"
                "Look at: src/cache.py:24\nIssues: {}\n").format(
                    verdict, risks or "none", issues or "none")

    def seed_review(self, verdict, issues="", risks="", head=None):
        task = chief.load_task("cache")
        task["review"] = dict(verdict=verdict, issues=issues, risks=risks,
                              head=head or self.head, by="claude/fixture",
                              at=chief.now_utc().isoformat(), summary="Cache changes reviewed.")
        chief.save_task(task)

    def collect(self):
        return chief.collect(self.cfg, persist=False)

    def current(self):
        return chief.load_task("cache")

    def cli(self, *args):
        chief.save_cfg(self.cfg)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = chief.main(list(args))
        self.assertEqual(code or 0, 0, err.getvalue())
        return out.getvalue()

    def surfaces(self, result):
        item = result["items"][0]
        entry = tui.entry(chief, item)
        return {"tasks": self.cli("tasks"), "show": self.cli("show", SID),
                "console": entry["headline"] + "\n" + "\n".join(t for _, t in entry["detail"]),
                "brief": chief.basic(result)}

    def assert_not_ready(self, item):
        self.assertNotEqual(chief.level_of(item), "green")
        self.assertNotEqual(item["task"]["state"], "review")
        for _, message, _ in item["signals"]:
            self.assertNotRegex(message, READY)

    def new_head(self, letter):
        self.head = letter * 40
        self.log["last_ts"] = chief.now_utc().isoformat()

    def cycle(self):
        # Either return immediately after review or on the next tick is valid.
        # Repeated ticks deliberately reload the task instead of sharing a dict.
        chief.tick(self.cfg)
        chief.tick(self.cfg)


class ReviewOutcomeDisplayTests(ReviewFixture):
    def test_review_enabled_by_default_waits_in_all_surfaces_without_green(self):
        result = self.collect()
        self.assert_not_ready(result["items"][0])
        for surface, text in self.surfaces(result).items():
            with self.subTest(surface=surface):
                self.assertRegex(text, WAITING)
                self.assertNotRegex(text, READY)

    def test_explicit_review_enabled_waits_without_green(self):
        self.cfg["review"] = True
        self.assert_not_ready(self.collect()["items"][0])

    def test_unchanged_task_still_says_waiting_for_cross_review(self):
        chief.collect(self.cfg)
        result = self.collect()
        self.assertFalse(result["items"][0]["changed"])
        self.assert_not_ready(result["items"][0])
        for surface, text in self.surfaces(result).items():
            with self.subTest(surface=surface):
                self.assertRegex(text, WAITING)

    def test_review_disabled_retains_checks_only_readiness(self):
        self.cfg["review"] = False
        item = self.collect()["items"][0]
        self.assertEqual(chief.level_of(item), "green")
        self.assertEqual(item["task"]["state"], "review")
        self.assertTrue(any(re.search(READY, m) for _, m, _ in item["signals"]))
        chief.tick(self.cfg)
        self.ai.assert_not_called()

    def test_pass_without_issues_is_ready_in_all_surfaces(self):
        self.seed_review("pass")
        result = self.collect()
        self.assertEqual(chief.level_of(result["items"][0]), "green")
        self.assertEqual(self.current()["state"], "review")
        for surface, text in self.surfaces(result).items():
            with self.subTest(surface=surface):
                self.assertRegex(text, READY)
                self.assertNotIn("ready with risks", text.lower())
                self.assertNotIn("needs work", text.lower())

    def test_concerns_without_issues_is_ready_with_visible_risks_everywhere(self):
        self.seed_review("concerns", risks=RISK)
        result = self.collect()
        item = result["items"][0]
        self.assertEqual(chief.level_of(item), "green")
        self.assertEqual(self.current()["state"], "review")
        headline = tui.entry(chief, item)["headline"]
        self.assertIn("ready with risks", headline.lower())
        self.assertIn(RISK, headline, "show risks beside the ready signal in the console row")
        for surface, text in self.surfaces(result).items():
            with self.subTest(surface=surface):
                self.assertIn("ready with risks", text.lower())
                self.assertIn(RISK, text)
        self.cycle()
        self.assertEqual(self.sent, [], "acceptable risks must not go back as mandatory work")

    def test_issues_override_every_verdict_and_are_never_ready(self):
        for verdict in ("pass", "concerns", "fail"):
            with self.subTest(verdict=verdict):
                self.seed_review(verdict, issues=ISSUE)
                result = self.collect()
                self.assert_not_ready(result["items"][0])
                for surface, text in self.surfaces(result).items():
                    with self.subTest(surface=surface):
                        self.assertIn("needs work", text.lower())
                        self.assertNotRegex(text, READY)
                        self.assertNotIn("ready with risks", text.lower())

    def test_fail_without_issues_is_needs_you_and_needs_work_everywhere(self):
        self.seed_review("fail")
        result = self.collect()
        self.assert_not_ready(result["items"][0])
        self.assertEqual(self.current()["state"], "needs-you")
        for surface, text in self.surfaces(result).items():
            with self.subTest(surface=surface):
                self.assertIn("needs work", text.lower())
                self.assertNotRegex(text, READY)
        self.cycle()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.current()["state"], "needs-you")

    def test_previous_head_review_does_not_make_current_head_ready(self):
        for verdict in ("pass", "concerns", "fail"):
            with self.subTest(verdict=verdict):
                self.seed_review(verdict, risks=RISK, head="b" * 40)
                result = self.collect()
                self.assert_not_ready(result["items"][0])
                for surface, text in self.surfaces(result).items():
                    with self.subTest(surface=surface):
                        self.assertRegex(text, WAITING)
                        self.assertNotIn(RISK, text, "stale risks must not describe the current HEAD")


class ReviewReturnTests(ReviewFixture):
    def test_parsed_issues_use_nudge_wording_once_per_head_and_are_logged(self):
        self.answer = self.review_text("concerns", issues=ISSUE)
        with mock.patch.object(chief, "nudge", wraps=chief.nudge) as nudge:
            self.cycle()
            self.assertEqual(len(self.sent), 1, "issues should return automatically")
            self.assertEqual(nudge.call_count, 1, "reuse the nudge-with-review path")
            args, kwargs = nudge.call_args
            self.assertTrue(kwargs.get("with_review") or (len(args) > 3 and args[3]))
            for _ in range(3):
                chief.tick(self.cfg)
            self.assertEqual(len(self.sent), 1, "the same reviewed HEAD is sent only once")
        self.ai.assert_called_once()
        self.assertIn("Independent review asked for these changes:\n" + ISSUE, self.sent[0])
        self.assertIn("Continue within the same boundaries.", self.sent[0])
        self.assertIn("Update .chief/progress.md, commit", self.sent[0])
        events = chief.events_since(self.current(), None)
        self.assertTrue(any("review" in e["text"].lower() and
                            ("automatic" in e["text"].lower() or "auto" in e["kind"].lower())
                            for e in events), "log that review issues were returned automatically")

    def test_issues_return_for_pass_and_fail_verdicts_too(self):
        for index, verdict in enumerate(("pass", "fail")):
            with self.subTest(verdict=verdict):
                self.new_head("bc"[index])
                self.seed_review(verdict, issues=ISSUE)
                self.cycle()
                self.assertEqual(len(self.sent), index + 1)

    def test_new_head_is_reviewed_again_and_can_return_new_issues(self):
        self.cfg["review_rounds"] = 3
        self.answer = self.review_text("concerns", issues=ISSUE)
        self.cycle()
        self.assertEqual(len(self.sent), 1)
        self.new_head("b")
        self.cycle()
        self.assertEqual(self.ai.call_count, 2)
        self.assertEqual(self.current()["review"]["head"], self.head)
        self.assertEqual(len(self.sent), 2)

    def assert_round_limit(self, limit):
        self.answer = self.review_text("fail", issues=ISSUE)
        for index in range(limit):
            self.new_head("abcd"[index])
            self.cycle()
            self.assertEqual(len(self.sent), index + 1)
        # The worker used every automatic return and still has concrete issues.
        self.new_head("e")
        self.cycle()
        self.assertEqual(len(self.sent), limit)
        self.assertEqual(self.ai.call_count, limit + 1)
        self.assertEqual(self.current()["state"], "needs-you")
        self.assertRegex(self.current().get("note", ""), r"(?i)review")
        self.assertIn(str(limit), self.current()["note"])
        self.assertRegex(self.current()["note"], r"(?i)limit|round|return")
        self.assertEqual(chief.level_of(self.collect()["items"][0]), "red")
        self.cycle()
        self.assertEqual(len(self.sent), limit)

    def test_default_limit_is_two_automatic_returns_persisted_across_ticks(self):
        self.assertNotIn("review_rounds", self.cfg)
        self.assert_round_limit(2)

    def test_configured_limit_counts_returns_despite_nudge_resetting_auto_state(self):
        self.cfg["review_rounds"] = 1
        self.assert_round_limit(1)

    def test_zero_round_limit_hands_issues_directly_to_user(self):
        self.cfg["review_rounds"] = 0
        self.assert_round_limit(0)

    def test_return_limit_is_per_task(self):
        self.cfg["review_rounds"] = 1
        self.answer = self.review_text("concerns", issues=ISSUE)
        self.cycle()
        self.assertEqual(len(self.sent), 1)
        completed = self.current()
        completed["state"] = "done"
        chief.save_task(completed)
        fresh = dict(self.task, id="cache-fresh", name="Another cache task")
        chief.save_task(fresh)
        self.cycle()
        self.assertEqual(len(self.sent), 2, "another task has its own automatic return allowance")
        self.assertEqual(chief.load_task("cache-fresh")["review"]["head"], self.head)

    def test_acceptable_review_after_last_return_is_ready_instead_of_capped(self):
        self.cfg["review_rounds"] = 1
        self.answer = self.review_text("concerns", issues=ISSUE)
        self.cycle()
        self.assertEqual(len(self.sent), 1)
        for letter, verdict, risks in (("b", "pass", ""), ("c", "concerns", RISK)):
            with self.subTest(verdict=verdict):
                self.new_head(letter)
                self.answer = self.review_text(verdict, risks=risks)
                self.cycle()
                item = self.collect()["items"][0]
                self.assertEqual(chief.level_of(item), "green")
                self.assertEqual(self.current()["state"], "review")
                self.assertEqual(len(self.sent), 1)

    def test_fail_without_issues_from_reviewer_goes_directly_to_needs_you(self):
        self.answer = self.review_text("fail")
        self.cycle()
        self.assertEqual(self.current()["review"]["issues"], "")
        self.assertEqual(self.current()["state"], "needs-you")
        self.assertEqual(self.sent, [])

    def test_pending_decision_suppresses_return_and_does_not_consume_a_round(self):
        self.cfg["review_rounds"] = 1
        self.seed_review("concerns", issues=ISSUE)
        self.log["footer"] = dict(decision="May I change the public API? Recommendation: wait.")
        self.cycle()
        self.assertEqual(self.sent, [])
        self.assertIsNotNone(self.collect()["items"][0].get("decision"))
        # A new turn retires that decision; the unused return is still available.
        self.log.update(footer={}, last_ts=chief.now_utc().isoformat())
        self.cycle()
        self.assertEqual(len(self.sent), 1)

    def test_user_presence_suppresses_return_then_allows_it_after_presence_expires(self):
        task = self.current()
        task.update(adopted=True, kickoff_at=chief.now_utc().isoformat())
        chief.save_task(task)
        self.seed_review("concerns", issues=ISSUE)
        self.log.update(last_prompt="I am inspecting this change", prompt_ts=chief.now_utc().isoformat())
        self.cycle()
        self.assertEqual(self.sent, [])
        self.log["prompt_ts"] = "2020-01-01T00:00:00+00:00"
        self.cycle()
        self.assertEqual(len(self.sent), 1)

    def test_presence_arriving_during_readiness_wait_suppresses_automatic_input(self):
        task = self.current()
        task.update(adopted=True, kickoff_at=chief.now_utc().isoformat())
        chief.save_task(task)
        self.seed_review("concerns", issues=ISSUE)

        def human_arrives(*args, **kwargs):
            self.log.update(last_prompt="I am inspecting this change", prompt_ts=chief.now_utc().isoformat())
            return "ready"

        with mock.patch.object(chief, "wait_ready", side_effect=human_arrives):
            chief.tick(self.cfg)
        self.assertEqual(self.sent, [])

    def test_dry_run_does_not_send_log_a_return_or_consume_a_round(self):
        self.cfg["review_rounds"] = 1
        self.seed_review("concerns", issues=ISSUE)
        for _ in range(3):
            chief.tick(self.cfg, dry=True)
        self.assertEqual(self.sent, [])
        self.ai.assert_not_called()
        self.assertFalse(any(e["kind"] == "nudge" for e in chief.events_since(self.current(), None)))
        self.cycle()
        self.assertEqual(len(self.sent), 1)

    def test_busy_worker_does_not_receive_review_issues_until_idle(self):
        self.seed_review("concerns", issues=ISSUE)
        self.status = "running"
        self.cycle()
        self.assertEqual(self.sent, [])
        self.status = "idle"
        self.cycle()
        self.assertEqual(len(self.sent), 1)

    def test_stale_review_issues_are_not_returned_for_current_head(self):
        self.seed_review("fail", issues=ISSUE, head="b" * 40)
        self.answer = self.review_text("pass")
        self.cycle()
        self.ai.assert_called_once()
        self.assertEqual(self.current()["review"]["head"], self.head)
        self.assertEqual(self.sent, [])


class ReviewerPromptTests(ReviewFixture):
    def test_prompt_reports_chief_check_result_and_grants_file_reading(self):
        chief.tick(self.cfg)
        self.ai.assert_called_once()
        args, kwargs = self.ai.call_args
        prompt = args[0]
        self.assertRegex(prompt, r"(?i)Chief (?:has (?:already )?)?ran .*checks")
        self.assertRegex(prompt, r"(?i)all 2 pass|2/2|2 of 2")
        self.assertRegex(prompt, r"(?i)(?:may|can) read files")
        self.assertIs(kwargs.get("read_files"), True)
        self.assertEqual(str(kwargs.get("cwd")), str(self.repo))

    def prompt_prose(self):
        return " ".join(chief.review_prompt(self.task, self.checks, "", "").split())

    def test_prompt_defines_concerns_as_acceptable_as_is(self):
        self.assertRegex(self.prompt_prose(),
                         r"(?i)concerns.{0,180}(?:acceptable as[ -]is|accept(?:able|ed)? without changes)")

    def test_prompt_requires_concrete_risks_with_file_line_references(self):
        self.assertRegex(self.prompt_prose(), r"(?i)risks.{0,160}(?:concrete|specific).{0,160}file:line")

    def test_prompt_puts_required_worker_changes_under_issues(self):
        self.assertRegex(self.prompt_prose(),
                         r"(?i)(?:must|required).{0,70}chang.{0,70}Issues|"
                         r"Issues.{0,70}(?:must|required).{0,70}chang|"
                         r"Issues.{0,70}chang.{0,70}(?:must|required)")

    def test_prompt_says_reviewer_not_running_tests_is_not_a_risk(self):
        self.assertRegex(self.prompt_prose(),
                         r"(?i)(?:not (?:having )?run|not running|did not run|haven.t run|lack of).{0,100}tests?"
                         r".{0,100}(?:not a risk|not itself a risk|not .{0,40}risk)|"
                         r"do not.{0,100}(?:risk|concern).{0,100}(?:not (?:having )?run|not running).{0,60}tests?")


if __name__ == "__main__":
    unittest.main()
